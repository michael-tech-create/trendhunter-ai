"""
TrendHunter AI — FastAPI app, REST routes, WebSocket streaming.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import get_settings
from log_config import setup_logging
from pipeline import DecisionPipeline

setup_logging()
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WS client connected (%s total)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("WS client disconnected (%s total)", len(self.active_connections))

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for c in dead:
            self.disconnect(c)


manager = ConnectionManager()
pipeline: Optional[DecisionPipeline] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline
    setup_logging()
    # dry_run_orders=True until Alpaca CLI is confirmed in the environment
    pipeline = DecisionPipeline(dry_run_orders=True, use_gemini=True)
    logger.info("TrendHunter backend ready. Watchlist=%s", get_settings().watchlist_tickers())
    yield


app = FastAPI(
    title="TrendHunter AI",
    description="Autonomous cash-secured put agent — paper trading",
    version="0.1.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list() or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    tickers: Optional[list[str]] = None
    contracts: int = Field(default=1, ge=1, le=10)
    use_gemini: Optional[bool] = None
    dry_run: Optional[bool] = None


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "trendhunter-ai"}


@app.get("/watchlist")
def get_watchlist() -> dict[str, Any]:
    return {"watchlist": get_settings().watchlist_tickers()}


@app.get("/portfolio")
def get_portfolio() -> dict[str, Any]:
    assert pipeline is not None
    return pipeline.portfolio_snapshot()


@app.get("/trades")
def get_trades(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    assert pipeline is not None
    return pipeline.list_trades(limit=limit)


@app.post("/scan")
async def trigger_scan(body: ScanRequest | None = None) -> dict[str, Any]:
    """Scan watchlist: signals → agent → risk gate → optional execution → autopsy."""
    assert pipeline is not None
    body = body or ScanRequest()
    if body.use_gemini is not None:
        pipeline.use_gemini = body.use_gemini
    if body.dry_run is not None:
        pipeline.dry_run_orders = body.dry_run

    results = await pipeline.scan_watchlist(
        tickers=body.tickers,
        broadcast=manager.broadcast,
        contracts=body.contracts,
    )
    return {
        "count": len(results),
        "executed": sum(1 for r in results if r.executed),
        "autopsies": [r.to_dict() for r in results],
        "portfolio": pipeline.portfolio_snapshot(),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            # Keep-alive / ignore client pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

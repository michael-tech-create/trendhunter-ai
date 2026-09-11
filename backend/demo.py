"""
Fast demo loop: 1–2 tickers, full pipeline, console autopsies.

  cd backend && python demo.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

# Ensure backend root on path when run as script
sys.path.insert(0, str(Path(__file__).resolve().parent))

from log_config import setup_logging
from pipeline import DecisionPipeline

setup_logging("INFO")
logger = logging.getLogger("demo")


async def on_event(message: dict) -> None:
    t = message.get("type", "?")
    ticker = message.get("ticker", "")
    if t == "trade_autopsy":
        data = message.get("data", {})
        logger.info(
            "AUTOPSY %s decision=%s gate=%s executed=%s",
            data.get("ticker"),
            data.get("decision"),
            data.get("risk_gate_approved"),
            data.get("executed"),
        )
        print(json.dumps(data, indent=2, default=str))
    else:
        logger.info("EVENT %s %s %s", t, ticker, {k: v for k, v in message.items() if k not in ("type", "ticker", "timestamp")})


async def main() -> None:
    tickers = sys.argv[1:] or ["AAPL", "MSFT"]
    pipe = DecisionPipeline(dry_run_orders=True, use_gemini=True)
    logger.info("Demo scan starting: %s", tickers)
    results = await pipe.scan_watchlist(tickers=tickers, broadcast=on_event, contracts=1)
    out = Path(__file__).parent / "data" / "last_demo_autopsies.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([r.to_dict() for r in results], indent=2, default=str))
    logger.info("Wrote %s (%s autopsies)", out, len(results))
    logger.info("Portfolio: %s", pipe.portfolio_snapshot())


if __name__ == "__main__":
    asyncio.run(main())

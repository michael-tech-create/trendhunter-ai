"""Paper trade execution via Alpaca CLI — cash-secured puts only."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from cli_wrapper import AlpacaCLIError, alpaca_cli_available, call_alpaca_cli
from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str]
    status: str
    raw: dict[str, Any]
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "order_id": self.order_id,
            "status": self.status,
            "error": self.error,
            "raw": self.raw,
        }


def _build_occ_symbol(ticker: str, expiry: str, strike: float, option_type: str) -> str:
    """Construct an OCC option contract symbol, e.g. AAPL260918P00322500."""
    exp = expiry.replace("-", "")[2:]  # YYYY-MM-DD -> YYMMDD
    type_char = "P" if option_type.lower().startswith("p") else "C"
    strike_int = int(round(strike * 1000))
    return f"{ticker.upper()}{exp}{type_char}{strike_int:08d}"
def submit_cash_secured_put(
    ticker: str,
    strike: float,
    expiry: str,
    contracts: int,
    *,
    dry_run: bool = False,
    limit_price: Optional[float] = None,
) -> OrderResult:
    """
    Submit a short put (cash-secured) on paper via Alpaca CLI.
    Never call this unless agent decision is SELL_PUT AND risk gate approved.
    Covered calls / multi-leg are intentionally unsupported.
    """
    import uuid

    ticker = ticker.upper().strip()
    if contracts <= 0:
        return OrderResult(False, None, "rejected", {}, "contracts must be positive")

    contract_symbol = _build_occ_symbol(ticker, expiry, strike, "put")

    if dry_run or not alpaca_cli_available():
        oid = f"DRYRUN-{contract_symbol}"
        logger.warning(
            "Dry-run CSP order %s x%s (CLI missing or dry_run=True)",
            contract_symbol,
            contracts,
        )
        return OrderResult(
            success=True,
            order_id=oid,
            status="dry_run_accepted",
            raw={
                "symbol": contract_symbol,
                "strike": strike,
                "expiry": expiry,
                "qty": contracts,
                "side": "sell",
                "option_type": "put",
            },
        )

    settings = get_settings()
    args = [
        "order",
        "submit",
        "--symbol",
        contract_symbol,
        "--side",
        "sell",
        "--qty",
        str(contracts),
        "--time-in-force",
        "day",
        "--client-order-id",
        str(uuid.uuid4()),
    ]
    # Prefer limit at mid when provided; else market (paper)
    if limit_price is not None:
        args.extend(["--type", "limit", "--limit-price", str(limit_price)])
    else:
        args.extend(["--type", "market"])

    try:
        raw = call_alpaca_cli(args)
        if not isinstance(raw, dict):
            raw = {"data": raw}
        order_id = (
            str(raw.get("id") or raw.get("order_id") or raw.get("client_order_id") or "")
            or None
        )
        status = str(raw.get("status") or "submitted")
        logger.info("Submitted CSP %s qty=%s order_id=%s", contract_symbol, contracts, order_id)
        return OrderResult(True, order_id, status, raw)
    except AlpacaCLIError as e:
        logger.error("Order submit failed: %s", e)
        return OrderResult(False, None, "error", {}, str(e))

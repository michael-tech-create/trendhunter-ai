"""Portfolio P&L and capital tracking helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass
class PortfolioSnapshot:
    capital_deployed: float
    open_positions: int
    premium_collected: float
    unrealized_pnl: float
    realized_pnl: float
    contracts_today: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "capital_deployed": self.capital_deployed,
            "open_positions": self.open_positions,
            "premium_collected": self.premium_collected,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "contracts_today": self.contracts_today,
        }


@dataclass
class PositionLike:
    """Minimal trade fields needed for P&L aggregation."""

    executed: bool
    strike: float
    contracts: int
    premium: float  # total credit dollars
    status: str = "open"  # open | closed


class PortfolioPnL:
    def __init__(self) -> None:
        self.realized_pnl: float = 0.0
        self._closed_premium: float = 0.0

    def snapshot(self, open_trades: Sequence[Any], *, contracts_today: int = 0) -> PortfolioSnapshot:
        """
        open_trades: objects with executed, strike, contracts, premium attributes
        and optional status (default open).
        """
        opens = [
            t
            for t in open_trades
            if getattr(t, "executed", False) and getattr(t, "status", "open") == "open"
        ]
        capital = sum(float(t.strike) * int(t.contracts) * 100.0 for t in opens)
        premium = sum(float(getattr(t, "premium", 0) or 0) for t in opens)
        # Unrealized: short put max risk shown as capital at risk (negative risk view)
        # Demo-friendly: mark unrealized as premium held (credit) until proper marks exist
        unrealized = premium  # credit received on open short puts
        return PortfolioSnapshot(
            capital_deployed=capital,
            open_positions=len(opens),
            premium_collected=premium + self._closed_premium,
            unrealized_pnl=unrealized,
            realized_pnl=self.realized_pnl,
            contracts_today=contracts_today,
        )

    def record_close(self, premium_kept: float, residual_pnl: float = 0.0) -> None:
        self.realized_pnl += premium_kept + residual_pnl
        self._closed_premium += premium_kept

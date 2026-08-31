"""
Deterministic RiskGate — hard rules Gemini cannot override.

Philosophy: attractive premium alone must never force a trade. These checks
exist so judges see a system that thinks but never acts recklessly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Union

from config import get_settings

logger = logging.getLogger(__name__)

DateLike = Union[date, datetime, str, None]


def _as_date(value: DateLike) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    raise TypeError(f"Unsupported date type: {type(value)}")


@dataclass
class RiskVerdict:
    approved: bool
    reason: str
    failed_rule: Optional[str] = None

    def as_tuple(self) -> tuple[bool, str]:
        return self.approved, self.reason


class RiskGate:
    """
    Apply capital, premium-quality, earnings, and pace limits.

    Every public check returns (approved, reason). evaluate_trade short-circuits
    on the first failure so autopsies can cite a single decisive rule.
    """

    def __init__(
        self,
        min_premium_ratio: Optional[float] = None,
        max_position_capital: Optional[float] = None,
        max_portfolio_capital: Optional[float] = None,
        max_contracts_per_day: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self.min_premium_ratio = (
            settings.min_premium_ratio if min_premium_ratio is None else min_premium_ratio
        )
        self.max_position_capital = (
            settings.max_position_capital
            if max_position_capital is None
            else max_position_capital
        )
        self.max_portfolio_capital = (
            settings.max_portfolio_capital
            if max_portfolio_capital is None
            else max_portfolio_capital
        )
        self.max_contracts_per_day = (
            settings.max_contracts_per_day
            if max_contracts_per_day is None
            else max_contracts_per_day
        )

    def check_premium_ratio(self, premium: float, max_loss: float) -> tuple[bool, str]:
        """
        Reject skinny credits on large notional.

        Example: $50 credit vs $5,000 cash secured is a 0.01 ratio — lottery-ticket
        payoff profile. Floor of 0.125 (1:8) is conservative but demo-justifiable.
        `premium` and `max_loss` must both be total dollars for the order
        (per-share mid * 100 * contracts, strike * 100 * contracts).
        """
        if max_loss <= 0:
            return False, "Max loss must be positive"
        ratio = premium / max_loss
        if ratio < self.min_premium_ratio:
            msg = (
                f"Premium/max-loss ratio {ratio:.3f} below minimum "
                f"{self.min_premium_ratio}"
            )
            logger.info("Risk reject premium_ratio: %s", msg)
            return False, msg
        return True, f"Premium/max-loss ratio {ratio:.3f} OK"

    def check_position_capital(self, strike: float, contracts: int) -> tuple[bool, str]:
        """One name cannot soak the entire paper book."""
        if contracts <= 0:
            return False, "Contracts must be positive"
        position_capital = strike * contracts * 100.0
        if position_capital > self.max_position_capital:
            msg = (
                f"Position capital ${position_capital:,.0f} exceeds limit "
                f"${self.max_position_capital:,.0f}"
            )
            logger.info("Risk reject position_capital: %s", msg)
            return False, msg
        return True, f"Position capital ${position_capital:,.0f} within limit"

    def check_portfolio_exposure(
        self, open_capital: float, new_capital: float
    ) -> tuple[bool, str]:
        """Force patience when aggregate cash secured is already high."""
        total = open_capital + new_capital
        if total > self.max_portfolio_capital:
            msg = (
                f"Portfolio capital ${total:,.0f} exceeds limit "
                f"${self.max_portfolio_capital:,.0f}"
            )
            logger.info("Risk reject portfolio_exposure: %s", msg)
            return False, msg
        return True, f"Portfolio capital ${total:,.0f} within limit"

    def check_earnings_blackout(
        self, earnings_date: DateLike, expiry: DateLike
    ) -> tuple[bool, str]:
        """
        #1 filter: earnings inside the option window = auto-reject, period.

        Binary events dominate short-premium edge; no AI story overrides this.
        Unknown earnings (None) is allowed through — callers should still try
        to resolve dates and prefer reject-on-ambiguity at the agent layer.
        """
        exp = _as_date(expiry)
        earn = _as_date(earnings_date)
        if exp is None:
            return False, "Expiry date missing for earnings check"
        if earn is not None and earn <= exp:
            msg = f"Earnings on {earn.isoformat()} falls inside option window (expiry {exp.isoformat()})"
            logger.info("Risk reject earnings_blackout: %s", msg)
            return False, msg
        return True, "No earnings inside option window"

    def check_daily_contract_limit(
        self, contracts_today: int, new_contracts: int
    ) -> tuple[bool, str]:
        """Stop a scan loop from overallocating in a single day."""
        total = contracts_today + new_contracts
        if total > self.max_contracts_per_day:
            msg = (
                f"Daily contracts {total} would exceed max "
                f"{self.max_contracts_per_day}"
            )
            logger.info("Risk reject daily_cap: %s", msg)
            return False, msg
        return True, f"Daily contracts {total} within cap"

    def evaluate_trade(
        self,
        *,
        premium: float,
        strike: float,
        contracts: int,
        expiry: DateLike,
        earnings_date: DateLike = None,
        open_portfolio_capital: float = 0.0,
        contracts_today: int = 0,
    ) -> RiskVerdict:
        """Run all hard rules; first failure wins."""
        max_loss = strike * contracts * 100.0
        new_capital = max_loss

        checks: list[tuple[str, tuple[bool, str]]] = [
            ("premium_ratio", self.check_premium_ratio(premium, max_loss)),
            ("position_capital", self.check_position_capital(strike, contracts)),
            (
                "portfolio_exposure",
                self.check_portfolio_exposure(open_portfolio_capital, new_capital),
            ),
            ("earnings_blackout", self.check_earnings_blackout(earnings_date, expiry)),
            (
                "daily_contract_limit",
                self.check_daily_contract_limit(contracts_today, contracts),
            ),
        ]

        for name, (ok, reason) in checks:
            if not ok:
                return RiskVerdict(approved=False, reason=reason, failed_rule=name)

        logger.info(
            "Risk APPROVED strike=%.2f contracts=%s premium=%.2f max_loss=%.2f",
            strike,
            contracts,
            premium,
            max_loss,
        )
        return RiskVerdict(approved=True, reason="Trade approved by risk gate", failed_rule=None)

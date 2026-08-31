"""Support / resistance helpers for cash-secured put strike selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SupportLevel:
    price: float
    method: str
    confidence: float  # 0–1 qualitative confidence in the level
    ma50: Optional[float] = None
    low_20d: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "method": self.method,
            "confidence": self.confidence,
            "ma50": self.ma50,
            "low_20d": self.low_20d,
        }


def analyze_support_level(history: pd.DataFrame) -> SupportLevel:
    """
    Estimate a recent support zone for CSP strike placement.

    Preference order:
    1. Blend of 20-day low and 50-day MA when both available (conservative cushion)
    2. 20-day low alone
    3. Last close * 0.95 as last-resort proxy

    Selling puts is safer when the strike sits at or slightly below a level
    the stock has already respected — not mid-air under a freefall.
    """
    if history is None or history.empty or "Close" not in history.columns:
        raise ValueError("history must include Close prices")

    close = history["Close"].astype(float)
    last_close = float(close.iloc[-1])

    low_series = history["Low"].astype(float) if "Low" in history.columns else close
    low_20d = float(low_series.tail(20).min()) if len(low_series) else last_close
    ma50 = float(close.tail(50).mean()) if len(close) >= 20 else None

    if ma50 is not None and low_20d > 0:
        # Use the higher of (slightly below spot cushion) candidates that still
        # sit under spot — we want support under the market, not above it.
        candidates = [p for p in (low_20d, ma50) if p < last_close]
        if candidates:
            # More conservative for short puts: higher support = less OTM cushion
            # but clearer technical reference. Take max of sub-spot supports.
            support = max(candidates)
            method = "max(20d_low, ma50) below spot"
            confidence = 0.7 if len(close) >= 50 else 0.55
        else:
            support = min(low_20d, last_close * 0.95)
            method = "compressed_range_fallback"
            confidence = 0.4
    else:
        support = low_20d if low_20d < last_close else last_close * 0.95
        method = "20d_low" if low_20d < last_close else "pct_below_spot"
        confidence = 0.5

    level = SupportLevel(
        price=round(support, 2),
        method=method,
        confidence=confidence,
        ma50=round(ma50, 2) if ma50 is not None else None,
        low_20d=round(low_20d, 2),
    )
    logger.info(
        "Support %.2f via %s (confidence=%.2f, spot=%.2f)",
        level.price,
        level.method,
        level.confidence,
        last_close,
    )
    return level


def suggest_put_strike(
    spot: float,
    support: SupportLevel,
    available_strikes: list[float],
    offset_pct: float = 0.05,
) -> Optional[float]:
    """
    Pick the listed put strike at or below target (support or spot*(1-offset)).

    Target prefers support when it is meaningfully below spot; otherwise
    spot * (1 - offset_pct). Among strikes <= target, choose the highest
    (closest to target) for a balance of premium vs cushion.
    """
    if not available_strikes:
        return None

    floor_target = spot * (1.0 - offset_pct)
    target = min(support.price, floor_target) if support.price < spot else floor_target

    below = sorted(s for s in available_strikes if s <= target)
    if not below:
        # No strike at/under target — take the lowest available if still below spot
        under_spot = sorted(s for s in available_strikes if s < spot)
        return under_spot[0] if under_spot else None

    return below[-1]

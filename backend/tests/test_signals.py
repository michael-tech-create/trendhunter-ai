"""Signal calculation tests on synthetic OHLCV."""

from __future__ import annotations

import numpy as np
import pandas as pd

from signals import signals_from_ohlcv


def _synthetic_ohlcv(n: int = 60, start: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    rets = rng.normal(0.0005, 0.01, size=n)
    close = start * np.cumprod(1 + rets)
    high = close * 1.01
    low = close * 0.99
    open_ = close * (1 + rng.normal(0, 0.001, size=n))
    volume = rng.integers(1_000_000, 5_000_000, size=n)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=idx,
    )


def test_signals_bounds() -> None:
    df = _synthetic_ohlcv()
    s = signals_from_ohlcv("TEST", df)
    assert s.ticker == "TEST"
    assert 0 < s.rsi < 100
    assert s.last_close > 0
    assert s.volume_ratio > 0
    assert s.volatility_20d >= 0

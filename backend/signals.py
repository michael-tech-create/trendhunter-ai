"""Market signal calculations from OHLCV (RSI, momentum, volume, volatility)."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Optional

import numpy as np
import pandas as pd
import yfinance as yf
from ta.momentum import RSIIndicator

logger = logging.getLogger(__name__)


@dataclass
class MarketSignals:
    ticker: str
    last_close: float
    rsi: float
    momentum_5d: float
    volume_ratio: float
    volatility_20d: float
    # Raw frame is not serialized by default
    history: Optional[pd.DataFrame] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "last_close": self.last_close,
            "rsi": self.rsi,
            "momentum_5d": self.momentum_5d,
            "volume_ratio": self.volume_ratio,
            "volatility_20d": self.volatility_20d,
        }


def fetch_market_data(ticker: str, days: int = 60) -> pd.DataFrame:
    """
    Fetch OHLCV and attach indicator columns.

    Why these signals:
    - RSI: avoid selling puts into extreme weakness without awareness
    - 5d momentum: short-term drift context for the thesis challenge
    - Volume ratio: participation / liquidity proxy on the underlying
    - 20d vol: realized vol backdrop vs option IV later
    """
    ticker = ticker.upper().strip()
    logger.info("Fetching market data for %s (%sd)", ticker, days)

    df = yf.download(ticker, period=f"{days}d", progress=False, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError(f"No market data returned for {ticker}")

    # yfinance may return MultiIndex columns for single tickers
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float)

    df = df.copy()
    df["rsi"] = RSIIndicator(close=close, window=14).rsi()
    df["momentum_5d"] = (close - close.shift(5)) / close.shift(5)
    df["volume_ratio"] = volume / volume.rolling(20).mean()
    df["volatility_20d"] = close.rolling(20).std() / close.rolling(20).mean()

    return df


def latest_signals(ticker: str, days: int = 60) -> MarketSignals:
    """Return the most recent signal snapshot for a ticker."""
    df = fetch_market_data(ticker, days=days)
    last = df.dropna(subset=["rsi", "momentum_5d", "volume_ratio", "volatility_20d"]).iloc[-1]

    signals = MarketSignals(
        ticker=ticker.upper().strip(),
        last_close=float(last["Close"]),
        rsi=float(last["rsi"]),
        momentum_5d=float(last["momentum_5d"]),
        volume_ratio=float(last["volume_ratio"]),
        volatility_20d=float(last["volatility_20d"]),
        history=df,
    )
    logger.info(
        "Signals %s: close=%.2f rsi=%.1f mom5=%.2f%% vol_ratio=%.2f hv20=%.3f",
        signals.ticker,
        signals.last_close,
        signals.rsi,
        signals.momentum_5d * 100,
        signals.volume_ratio,
        signals.volatility_20d,
    )
    return signals


def signals_from_ohlcv(ticker: str, df: pd.DataFrame) -> MarketSignals:
    """Compute signals from a pre-built OHLCV frame (tests / cache)."""
    if df.empty:
        raise ValueError("OHLCV frame is empty")

    work = df.copy()
    close = work["Close"].astype(float)
    volume = work["Volume"].astype(float)
    work["rsi"] = RSIIndicator(close=close, window=14).rsi()
    work["momentum_5d"] = (close - close.shift(5)) / close.shift(5)
    work["volume_ratio"] = volume / volume.rolling(20).mean()
    work["volatility_20d"] = close.rolling(20).std() / close.rolling(20).mean()

    valid = work.dropna(subset=["rsi", "momentum_5d", "volume_ratio", "volatility_20d"])
    if valid.empty:
        # Fallback for short fixtures: use last row with nan->neutral defaults
        last = work.iloc[-1]
        return MarketSignals(
            ticker=ticker.upper(),
            last_close=float(last["Close"]),
            rsi=float(last["rsi"]) if pd.notna(last.get("rsi")) else 50.0,
            momentum_5d=float(last["momentum_5d"]) if pd.notna(last.get("momentum_5d")) else 0.0,
            volume_ratio=float(last["volume_ratio"]) if pd.notna(last.get("volume_ratio")) else 1.0,
            volatility_20d=float(last["volatility_20d"]) if pd.notna(last.get("volatility_20d")) else 0.0,
            history=work,
        )

    last = valid.iloc[-1]
    return MarketSignals(
        ticker=ticker.upper(),
        last_close=float(last["Close"]),
        rsi=float(last["rsi"]),
        momentum_5d=float(last["momentum_5d"]),
        volume_ratio=float(last["volume_ratio"]),
        volatility_20d=float(last["volatility_20d"]),
        history=work,
    )

"""Earnings date lookup — feeds the hard risk blackout."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)


def check_earnings_date(ticker: str, after: Optional[date] = None) -> Optional[date]:
    """
    Return the next known earnings date on/after `after` (default: today), or None.

    Prefer rejecting when ambiguous at the agent layer; RiskGate only blocks when
    a concrete date falls on or before expiry.
    """
    ticker = ticker.upper().strip()
    after = after or date.today()
    try:
        t = yf.Ticker(ticker)
        # calendar may be dict or DataFrame depending on yfinance version
        cal = getattr(t, "calendar", None)
        earnings_ts = None

        if isinstance(cal, dict):
            earnings_ts = cal.get("Earnings Date") or cal.get("earningsDate")
            if isinstance(earnings_ts, (list, tuple)) and earnings_ts:
                earnings_ts = earnings_ts[0]
        elif cal is not None:
            try:
                # DataFrame style
                if hasattr(cal, "loc") and "Earnings Date" in getattr(cal, "index", []):
                    val = cal.loc["Earnings Date"]
                    earnings_ts = val.iloc[0] if hasattr(val, "iloc") else val
            except Exception:
                earnings_ts = None

        # earnings_dates DataFrame (newer yfinance)
        if earnings_ts is None:
            try:
                ed = t.earnings_dates
                if ed is not None and len(ed) > 0:
                    for idx in ed.index:
                        ts = idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx
                        if isinstance(ts, datetime):
                            d = ts.date()
                        elif isinstance(ts, date):
                            d = ts
                        else:
                            continue
                        if d >= after:
                            logger.info("Earnings %s: %s", ticker, d.isoformat())
                            return d
            except Exception as e:
                logger.debug("earnings_dates unavailable for %s: %s", ticker, e)

        if earnings_ts is None:
            logger.info("No earnings date found for %s", ticker)
            return None

        if isinstance(earnings_ts, datetime):
            d = earnings_ts.date()
        elif isinstance(earnings_ts, date):
            d = earnings_ts
        else:
            d = date.fromisoformat(str(earnings_ts)[:10])

        if d >= after:
            logger.info("Earnings %s: %s", ticker, d.isoformat())
            return d
        return None
    except Exception as e:
        logger.warning("Earnings lookup failed for %s: %s", ticker, e)
        return None

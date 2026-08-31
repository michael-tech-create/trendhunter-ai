"""Option chain helpers, IV rank, and cash-secured put candidate selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import yfinance as yf

from cli_wrapper import AlpacaCLIError, call_alpaca_cli
from config import get_settings
from technical import SupportLevel, analyze_support_level, suggest_put_strike

logger = logging.getLogger(__name__)


@dataclass
class OptionContract:
    symbol: str
    underlying: str
    strike: float
    expiry: str
    option_type: str  # put | call
    bid: float
    ask: float
    mid: float
    iv: Optional[float] = None
    open_interest: Optional[int] = None

    @property
    def spread_pct(self) -> float:
        if self.mid <= 0:
            return 1.0
        return (self.ask - self.bid) / self.mid

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "underlying": self.underlying,
            "strike": self.strike,
            "expiry": self.expiry,
            "option_type": self.option_type,
            "bid": self.bid,
            "ask": self.ask,
            "mid": self.mid,
            "iv": self.iv,
            "open_interest": self.open_interest,
            "spread_pct": self.spread_pct,
        }


@dataclass
class PutCandidate:
    contract: OptionContract
    iv_rank: float
    support: SupportLevel
    spot: float
    premium_dollars_per_contract: float
    max_loss_per_contract: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract.to_dict(),
            "iv_rank": self.iv_rank,
            "support": self.support.to_dict(),
            "spot": self.spot,
            "premium_dollars_per_contract": self.premium_dollars_per_contract,
            "max_loss_per_contract": self.max_loss_per_contract,
            "reasons": self.reasons,
        }


def target_expiry(days_to_expiry: Optional[int] = None, from_day: Optional[date] = None) -> str:
    """Pick a calendar target expiry date string (YYYY-MM-DD)."""
    settings = get_settings()
    dte = days_to_expiry if days_to_expiry is not None else settings.default_days_to_expiry
    base = from_day or date.today()
    # Prefer Friday near target DTE
    target = base + timedelta(days=dte)
    # Roll forward to Friday (weekday 4)
    while target.weekday() != 4:
        target += timedelta(days=1)
    return target.isoformat()


def calculate_iv_rank(current_iv: float, iv_history: list[float]) -> float:
    """IV percentile vs history (0–100). Empty history → neutral 50."""
    if not iv_history:
        return 50.0
    below = sum(1 for iv in iv_history if iv < current_iv)
    return (below / len(iv_history)) * 100.0


def estimate_iv_history_from_realized(ticker: str, lookback_days: int = 252) -> list[float]:
    """
    Proxy IV history using rolling realized vol when a true IV time series
    is unavailable (common in hackathon / yfinance-only setups).
    """
    try:
        df = yf.download(ticker, period=f"{min(lookback_days + 40, 400)}d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return []
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        close = df["Close"].astype(float)
        rets = close.pct_change().dropna()
        # 20-day realized vol annualized
        rv = rets.rolling(20).std() * (252**0.5)
        vals = [float(x) for x in rv.dropna().tolist() if x == x]
        return vals[-lookback_days:]
    except Exception as e:
        logger.warning("IV history proxy failed for %s: %s", ticker, e)
        return []


def fetch_option_chain(ticker: str, expiry: str) -> list[OptionContract]:
    """
    Fetch option chain via Alpaca CLI when available; else yfinance fallback.

    CLI shape varies by version — we normalize defensively into OptionContract.
    """
    ticker = ticker.upper().strip()
    settings = get_settings()

    try:
        raw = call_alpaca_cli(
            ["data", "option", "--symbol", ticker, "--expiry", expiry],
        )
        contracts = _normalize_chain(raw, ticker, expiry)
        if contracts:
            logger.info("CLI chain %s %s: %s contracts", ticker, expiry, len(contracts))
            return contracts
    except AlpacaCLIError as e:
        logger.warning("Alpaca CLI chain failed, trying yfinance: %s", e)

    return _yf_option_chain(ticker, expiry)


def _normalize_chain(raw: Any, ticker: str, expiry: str) -> list[OptionContract]:
    rows: list[Any]
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, dict):
        for key in ("options", "contracts", "data", "results", "quotes"):
            if isinstance(raw.get(key), list):
                rows = raw[key]
                break
        else:
            rows = [raw]
    else:
        return []

    out: list[OptionContract] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            opt_type = str(row.get("type") or row.get("option_type") or row.get("optionType") or "").lower()
            if opt_type and opt_type not in ("put", "p", "call", "c"):
                # try to infer from symbol
                opt_type = "put" if "P" in str(row.get("symbol", ""))[-9:] else ""
            if opt_type in ("p",):
                opt_type = "put"
            if opt_type in ("c",):
                opt_type = "call"

            strike = float(row.get("strike") or row.get("strike_price") or row.get("strikePrice"))
            bid = float(row.get("bid") or row.get("bid_price") or 0)
            ask = float(row.get("ask") or row.get("ask_price") or 0)
            mid = float(row.get("mid") or ((bid + ask) / 2 if bid or ask else row.get("last") or 0))
            iv_raw = row.get("iv") or row.get("implied_volatility") or row.get("impliedVolatility")
            iv = float(iv_raw) if iv_raw is not None else None
            symbol = str(row.get("symbol") or row.get("contract_symbol") or f"{ticker}{expiry}{strike}")
            exp = str(row.get("expiry") or row.get("expiration") or row.get("expiration_date") or expiry)[:10]
            oi = row.get("open_interest") or row.get("openInterest")
            out.append(
                OptionContract(
                    symbol=symbol,
                    underlying=ticker,
                    strike=strike,
                    expiry=exp,
                    option_type=opt_type or "put",
                    bid=bid,
                    ask=ask,
                    mid=mid,
                    iv=iv,
                    open_interest=int(oi) if oi is not None else None,
                )
            )
        except (TypeError, ValueError, KeyError):
            continue
    return out


def _yf_option_chain(ticker: str, expiry: str) -> list[OptionContract]:
    """yfinance fallback for paper/demo when CLI is missing."""
    t = yf.Ticker(ticker)
    expiries = list(t.options or [])
    if not expiries:
        logger.error("No yfinance option expiries for %s", ticker)
        return []

    # Nearest expiry on/after requested date
    chosen = expiry
    if expiry not in expiries:
        future = [e for e in expiries if e >= expiry]
        chosen = future[0] if future else expiries[-1]
        logger.info("Adjusted expiry %s → %s for %s", expiry, chosen, ticker)

    chain = t.option_chain(chosen)
    puts = chain.puts
    out: list[OptionContract] = []
    for _, row in puts.iterrows():
        bid = float(row.get("bid") or 0)
        ask = float(row.get("ask") or 0)
        last = float(row.get("lastPrice") or 0)
        mid = (bid + ask) / 2 if bid or ask else last
        iv = row.get("impliedVolatility")
        out.append(
            OptionContract(
                symbol=str(row.get("contractSymbol") or ""),
                underlying=ticker,
                strike=float(row["strike"]),
                expiry=chosen,
                option_type="put",
                bid=bid,
                ask=ask,
                mid=float(mid),
                iv=float(iv) if iv == iv else None,
                open_interest=int(row["openInterest"]) if row.get("openInterest") == row.get("openInterest") else None,
            )
        )
    logger.info("yfinance chain %s %s: %s puts", ticker, chosen, len(out))
    return out


def select_candidate_puts(
    ticker: str,
    history,
    spot: float,
    chain: list[OptionContract],
    *,
    min_premium: Optional[float] = None,
    max_spread_pct: Optional[float] = None,
) -> Optional[PutCandidate]:
    """
    Choose a single liquid OTM/ATM-support put for CSP analysis.

    Filters:
    - puts only
    - bid-ask spread under threshold (illiquid premium is a trap)
    - mid premium >= min
    - strike near support / offset below spot
    """
    settings = get_settings()
    min_premium = settings.min_option_premium if min_premium is None else min_premium
    max_spread_pct = settings.max_bid_ask_spread_pct if max_spread_pct is None else max_spread_pct

    support = analyze_support_level(history)
    puts = [c for c in chain if c.option_type == "put"]

    def _usable(c: OptionContract) -> bool:
        # yfinance often prints bid=0 on cheap names; allow last/mid-only quotes
        return c.mid >= min_premium and c.strike < spot

    liquid = [
        c
        for c in puts
        if _usable(c) and c.bid > 0 and c.spread_pct <= max_spread_pct
    ]
    if not liquid:
        # Relax spread; still prefer a real bid
        liquid = [c for c in puts if _usable(c) and c.bid > 0]
    if not liquid:
        # Last resort: mid-only quotes (common on yfinance for low-priced underlyings)
        liquid = [c for c in puts if _usable(c)]
        logger.info(
            "Relaxed liquidity filter for %s: using mid-only quotes (%s)",
            ticker,
            len(liquid),
        )
    if not liquid:
        logger.info("No liquid put candidates for %s", ticker)
        return None

    strikes = [c.strike for c in liquid]
    chosen_strike = suggest_put_strike(
        spot, support, strikes, offset_pct=settings.strike_offset_pct
    )
    if chosen_strike is None:
        return None

    # Prefer contracts near the support-based target, but among nearby strikes
    # score by premium/max_loss so we do not systematically pick worthless far-OTM shells.
    # RiskGate still enforces the hard 0.125 floor — selection only improves the candidate set.
    nearby = sorted(liquid, key=lambda c: abs(c.strike - chosen_strike))[:8]

    def _score(c: OptionContract) -> float:
        notional = c.strike * 100.0
        if notional <= 0 or c.mid <= 0:
            return -1.0
        ratio = (c.mid * 100.0) / notional
        # Distance penalty from technical target (in % of spot)
        dist = abs(c.strike - chosen_strike) / max(spot, 1e-6)
        return ratio - 0.15 * dist

    contract = max(nearby, key=_score)
    iv_hist = estimate_iv_history_from_realized(ticker)
    current_iv = contract.iv if contract.iv is not None else (iv_hist[-1] if iv_hist else 0.25)
    # yfinance IV is often already a decimal vol; realized proxy too
    iv_rank = calculate_iv_rank(float(current_iv), iv_hist)

    premium_dollars = contract.mid * 100.0
    max_loss = contract.strike * 100.0  # cash-secured notional per contract

    reasons = [
        f"Strike {contract.strike} near support {support.price} ({support.method})",
        f"Mid premium ${contract.mid:.2f} (bid {contract.bid:.2f} / ask {contract.ask:.2f})",
        f"IV rank ~{iv_rank:.0f}th percentile",
        f"Premium/max-loss preview {premium_dollars / max_loss:.3f}",
    ]
    return PutCandidate(
        contract=contract,
        iv_rank=iv_rank,
        support=support,
        spot=spot,
        premium_dollars_per_contract=premium_dollars,
        max_loss_per_contract=max_loss,
        reasons=reasons,
    )


def load_cached_chain(path: str | Path) -> list[OptionContract]:
    """Load normalized contracts from demo cache JSON."""
    import json

    data = json.loads(Path(path).read_text())
    return _normalize_chain(data.get("contracts", data), data.get("ticker", "UNKNOWN"), data.get("expiry", ""))

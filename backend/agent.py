"""
Gemini agent reasoning — hunt for reasons NOT to sell cash-secured puts.

If the API key is missing or the SDK call fails, fall back to a deterministic
heuristic decision so demos and tests still produce autopsies.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

from config import get_settings
from earnings import check_earnings_date
from options import PutCandidate, calculate_iv_rank, estimate_iv_history_from_realized
from technical import SupportLevel
from trade_autopsy import AgentDecision

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are TrendHunter AI, an autonomous options-selling agent. Your core mission is NOT to find every possible trade.
Your mission is to find trades that are worth the risk, and to explicitly reject trades where the setup is flawed.

When analyzing a cash-secured put candidate, you MUST:

1. Inspect the option chain: strike, expiry, bid/ask spread, implied volatility, premium.
2. Challenge the thesis: hunt for evidence AGAINST the trade.
   - Earnings inside the option window?
   - IV low vs this stock's history?
   - Strike safely at/above recent support?
   - Wide bid-ask (illiquid)?
3. Evaluate technical setup: support, momentum neutral or constructive.
4. Consider IV context: is premium attractive vs IV rank?
5. Decide clearly:
   - SELL_PUT (confidence 0.7–1.0): checks passed, risk justified.
   - WAIT (0.4–0.7): reasonable but timing/IV unclear; revisit soon.
   - AVOID (0.0–0.4): contradictory evidence; risk not justified.

Treat AVOID and WAIT as successful decisions. Do not force SELL_PUT just because premium is attractive.
Explanations must be clear, concise, and backed by tools/context provided.

Respond with ONLY valid JSON:
{
  "decision": "SELL_PUT" | "WAIT" | "AVOID",
  "confidence": 0.0-1.0,
  "reasoning": "string",
  "supporting_factors": ["..."],
  "contradicting_factors": ["..."]
}
"""


def _tool_context(
    ticker: str,
    candidate: PutCandidate,
    signals: dict[str, Any],
    earnings,
) -> dict[str, Any]:
    c = candidate.contract
    return {
        "ticker": ticker,
        "signals": signals,
        "option": c.to_dict(),
        "iv_rank": candidate.iv_rank,
        "support": candidate.support.to_dict(),
        "spot": candidate.spot,
        "earnings_date": earnings.isoformat() if earnings else None,
        "premium_dollars_per_contract": candidate.premium_dollars_per_contract,
        "max_loss_per_contract": candidate.max_loss_per_contract,
        "spread_pct": c.spread_pct,
    }


def heuristic_decision(
    ticker: str,
    candidate: PutCandidate,
    signals: dict[str, Any],
    earnings,
) -> AgentDecision:
    """
    Local skeptical policy used when Gemini is unavailable.

    Mirrors the spirit of the system prompt: earnings and low IV rank push AVOID;
    mediocre setups WAIT; only cleaner IV + support alignment may SELL_PUT.
    """
    supporting: list[str] = []
    contradicting: list[str] = []
    c = candidate.contract

    if c.strike <= candidate.support.price * 1.02:
        supporting.append(
            f"Strike {c.strike} sits near support {candidate.support.price}"
        )
    else:
        contradicting.append(
            f"Strike {c.strike} is above mapped support {candidate.support.price}"
        )

    if candidate.iv_rank >= 40:
        supporting.append(f"IV rank {candidate.iv_rank:.0f} suggests non-depressed premium")
    elif candidate.iv_rank < 25:
        contradicting.append(
            f"IV rank {candidate.iv_rank:.0f}th percentile — premium looks cheap vs history"
        )
    else:
        contradicting.append(f"IV rank {candidate.iv_rank:.0f} only middling")

    if c.spread_pct <= 0.05:
        supporting.append(f"Bid-ask spread {c.spread_pct:.1%} acceptable")
    else:
        contradicting.append(f"Wide bid-ask spread {c.spread_pct:.1%} (liquidity risk)")

    rsi = float(signals.get("rsi") or 50)
    mom = float(signals.get("momentum_5d") or 0)
    if rsi < 30:
        contradicting.append(f"RSI {rsi:.0f} oversold — elevated downside follow-through risk")
    elif rsi <= 60:
        supporting.append(f"RSI {rsi:.0f} not euphoric")
    if mom < -0.05:
        contradicting.append(f"5d momentum {mom:.1%} weak")

    if earnings and c.expiry and str(earnings) <= str(c.expiry)[:10]:
        contradicting.append(
            f"Earnings on {earnings.isoformat()} inside option window (expiry {c.expiry})"
        )

    # Decision policy
    if any("Earnings" in x for x in contradicting) or candidate.iv_rank < 20:
        decision, conf = "AVOID", 0.25
    elif len(contradicting) >= 2 or candidate.iv_rank < 30:
        decision, conf = "AVOID" if len(contradicting) >= 3 else "WAIT", 0.35 if len(contradicting) >= 3 else 0.55
    elif len(contradicting) == 0 and candidate.iv_rank >= 45:
        decision, conf = "SELL_PUT", 0.8
    elif len(contradicting) <= 1 and candidate.iv_rank >= 35:
        decision, conf = "SELL_PUT", 0.72
    else:
        decision, conf = "WAIT", 0.5

    reasoning = (
        f"Heuristic analysis for {ticker} CSP @ {c.strike} exp {c.expiry}. "
        f"IV rank={candidate.iv_rank:.0f}, spread={c.spread_pct:.1%}, "
        f"support={candidate.support.price}. "
        + (
            "Contradictions dominate — declining trade."
            if decision != "SELL_PUT"
            else "Setup clears local skepticism checks; risk gate still required."
        )
    )
    return AgentDecision(
        decision=decision,
        confidence=conf,
        reasoning=reasoning,
        supporting_factors=supporting,
        contradicting_factors=contradicting,
    )


def _parse_decision_json(text: str) -> AgentDecision:
    text = text.strip()
    # Strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]
    data = json.loads(text)
    decision = str(data.get("decision", "AVOID")).upper()
    if decision not in ("SELL_PUT", "WAIT", "AVOID"):
        decision = "AVOID"
    return AgentDecision(
        decision=decision,
        confidence=float(data.get("confidence", 0.3)),
        reasoning=str(data.get("reasoning", "")),
        supporting_factors=list(data.get("supporting_factors") or []),
        contradicting_factors=list(data.get("contradicting_factors") or []),
    )


def _gemini_decide(context: dict[str, Any]) -> AgentDecision:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    try:
        from google import genai
    except ImportError as e:
        raise RuntimeError("google-genai package not installed") from e

    client = genai.Client(api_key=settings.gemini_api_key)
    user_prompt = (
        "Analyze this cash-secured put candidate and respond with JSON only.\n\n"
        + json.dumps(context, indent=2, default=str)
    )
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=user_prompt,
        config={
            "system_instruction": SYSTEM_PROMPT,
            "temperature": 0.2,
        },
    )
    text = getattr(response, "text", None) or str(response)
    return _parse_decision_json(text)


def analyze_candidate(
    ticker: str,
    candidate: PutCandidate,
    signals: dict[str, Any],
    *,
    earnings=None,
    use_gemini: bool = True,
) -> AgentDecision:
    """
    Produce SELL_PUT / WAIT / AVOID for a CSP candidate.

    Always enriches with earnings when not provided. Gemini is preferred;
    heuristic fallback keeps the pipeline demoable offline.
    """
    ticker = ticker.upper().strip()
    if earnings is None:
        from datetime import date

        earnings = check_earnings_date(ticker, after=date.today())

    context = _tool_context(ticker, candidate, signals, earnings)
    logger.info("Agent analyzing %s strike=%s exp=%s", ticker, candidate.contract.strike, candidate.contract.expiry)

    if use_gemini:
        try:
            decision = _gemini_decide(context)
            logger.info("Gemini decision %s conf=%.2f", decision.decision, decision.confidence)
            return decision
        except Exception as e:
            logger.warning("Gemini unavailable (%s); using heuristic agent", e)

    decision = heuristic_decision(ticker, candidate, signals, earnings)
    logger.info("Heuristic decision %s conf=%.2f", decision.decision, decision.confidence)
    return decision


# --- Explicit tool callables (for future full tool-calling loop / MCP) ---

def tool_check_earnings_date(ticker: str) -> Optional[str]:
    d = check_earnings_date(ticker)
    return d.isoformat() if d else None


def tool_calculate_iv_percentile(ticker: str, current_iv: float) -> float:
    hist = estimate_iv_history_from_realized(ticker)
    return calculate_iv_rank(current_iv, hist)


def tool_assess_liquidity(bid: float, ask: float, mid: float) -> dict[str, str]:
    if mid <= 0:
        return {"status": "Illiquid", "reason": "Non-positive mid"}
    spread = (ask - bid) / mid
    if spread <= 0.05:
        return {"status": "Liquid", "reason": f"Spread {spread:.1%} <= 5%"}
    return {"status": "Illiquid", "reason": f"Spread {spread:.1%} > 5%"}

"""Structured Trade Autopsy — every decision must be judge-readable."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from options import PutCandidate
from risk_engine import RiskVerdict

logger = logging.getLogger(__name__)


class AgentDecision(BaseModel):
    """Normalized agent output (SELL_PUT | WAIT | AVOID)."""

    decision: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    supporting_factors: list[str] = Field(default_factory=list)
    contradicting_factors: list[str] = Field(default_factory=list)


class TradeAutopsy(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    ticker: str
    decision: str
    confidence: float
    strike: Optional[float] = None
    expiry: Optional[str] = None
    premium: Optional[float] = None
    breakeven: Optional[float] = None
    max_loss: Optional[float] = None
    iv_rank: Optional[float] = None
    risk_level: str = "Medium"
    supporting_factors: list[str] = Field(default_factory=list)
    contradicting_factors: list[str] = Field(default_factory=list)
    position_size: dict[str, Any] = Field(default_factory=dict)
    invalidation_criteria: list[str] = Field(default_factory=list)
    risk_gate_approved: bool = False
    risk_gate_reason: str = ""
    risk_gate_failed_rule: Optional[str] = None
    executed: bool = False
    order_id: Optional[str] = None
    reasoning: str = ""
    signals: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


def _risk_level(iv_rank: Optional[float], gate: RiskVerdict, decision: str) -> str:
    if not gate.approved or decision == "AVOID":
        return "High"
    if iv_rank is not None and iv_rank < 30:
        return "High"  # cheap premium relative to history
    if iv_rank is not None and iv_rank >= 50 and decision == "SELL_PUT" and gate.approved:
        return "Low"
    return "Medium"


def generate_autopsy(
    *,
    ticker: str,
    decision: AgentDecision,
    candidate: Optional[PutCandidate] = None,
    risk: Optional[RiskVerdict] = None,
    contracts: int = 0,
    signals: Optional[dict[str, Any]] = None,
    executed: bool = False,
    order_id: Optional[str] = None,
    extra_invalidation: Optional[list[str]] = None,
) -> TradeAutopsy:
    """
    Build a full autopsy from agent + gate (+ optional candidate).

    Critical path: Gemini may say SELL_PUT while the gate rejects (e.g. earnings).
    Both must appear — supporting/contradicting factors and risk_gate_* fields —
    so a judge never wonders why no order was sent.
    """
    risk = risk or RiskVerdict(approved=False, reason="Risk gate not evaluated", failed_rule=None)

    supporting = list(decision.supporting_factors)
    contradicting = list(decision.contradicting_factors)

    strike = expiry = premium = breakeven = max_loss = iv_rank = None
    position_size: dict[str, Any] = {"contracts": contracts, "capital": 0.0}

    if candidate is not None:
        c = candidate.contract
        strike = c.strike
        expiry = c.expiry
        # Store per-share mid and total credit for the order size
        premium_per_share = c.mid
        premium = premium_per_share * 100.0 * max(contracts, 1)
        breakeven = c.strike - premium_per_share
        max_loss = c.strike * 100.0 * max(contracts, 1)
        iv_rank = candidate.iv_rank
        position_size = {
            "contracts": contracts,
            "capital": c.strike * 100.0 * max(contracts, 1),
            "premium_credit": premium if contracts else candidate.premium_dollars_per_contract,
        }
        for r in candidate.reasons:
            if r not in supporting:
                supporting.append(r)

    # Gate rejection is always a contradicting factor when agent wanted to sell
    if decision.decision == "SELL_PUT" and not risk.approved:
        gate_factor = f"Risk gate rejected: {risk.reason}"
        if gate_factor not in contradicting:
            contradicting.append(gate_factor)

    if not risk.approved and risk.reason and risk.reason not in contradicting:
        # Still surface gate reason on WAIT/AVOID paths when evaluated
        if decision.decision == "SELL_PUT":
            pass  # already added
        elif risk.failed_rule:
            contradicting.append(f"Risk gate: {risk.reason}")

    invalidation = list(extra_invalidation or [])
    if strike is not None:
        invalidation.append(f"Underlying closes materially below support near strike {strike}")
    if expiry:
        invalidation.append(f"Hold thesis only through expiry {expiry}; do not roll blindly")
    if iv_rank is not None and iv_rank < 30:
        invalidation.append("IV rank depressed — premium may not compensate tail risk")

    # Final actionable decision label for storage: agent intent stays in `decision`,
    # executed flag shows whether paper order went out.
    will_execute = bool(
        executed and decision.decision == "SELL_PUT" and risk.approved
    )

    autopsy = TradeAutopsy(
        ticker=ticker.upper(),
        decision=decision.decision,
        confidence=decision.confidence,
        strike=strike,
        expiry=expiry,
        premium=premium,
        breakeven=breakeven,
        max_loss=max_loss,
        iv_rank=iv_rank,
        risk_level=_risk_level(iv_rank, risk, decision.decision),
        supporting_factors=supporting,
        contradicting_factors=contradicting,
        position_size=position_size,
        invalidation_criteria=invalidation,
        risk_gate_approved=risk.approved,
        risk_gate_reason=risk.reason,
        risk_gate_failed_rule=risk.failed_rule,
        executed=will_execute,
        order_id=order_id if will_execute else None,
        reasoning=decision.reasoning,
        signals=signals or {},
    )
    logger.info(
        "Autopsy %s %s conf=%.2f gate=%s executed=%s",
        autopsy.ticker,
        autopsy.decision,
        autopsy.confidence,
        autopsy.risk_gate_approved,
        autopsy.executed,
    )
    return autopsy

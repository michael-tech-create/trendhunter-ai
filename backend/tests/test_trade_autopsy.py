"""Autopsy generation — especially SELL_PUT + gate reject."""

from __future__ import annotations

from options import OptionContract, PutCandidate
from risk_engine import RiskVerdict
from technical import SupportLevel
from trade_autopsy import AgentDecision, generate_autopsy


def _candidate() -> PutCandidate:
    contract = OptionContract(
        symbol="AAPL240919P00150000",
        underlying="AAPL",
        strike=150.0,
        expiry="2026-09-18",
        option_type="put",
        bid=2.0,
        ask=2.2,
        mid=2.1,
        iv=0.28,
    )
    return PutCandidate(
        contract=contract,
        iv_rank=18.0,
        support=SupportLevel(price=148.0, method="20d_low", confidence=0.6),
        spot=160.0,
        premium_dollars_per_contract=210.0,
        max_loss_per_contract=15000.0,
        reasons=["Strike near support"],
    )


def test_autopsy_sell_put_gate_reject_records_both() -> None:
    decision = AgentDecision(
        decision="SELL_PUT",
        confidence=0.85,
        reasoning="Premium looks attractive",
        supporting_factors=["Fat premium"],
        contradicting_factors=[],
    )
    risk = RiskVerdict(
        approved=False,
        reason="Earnings on 2026-09-15 falls inside option window (expiry 2026-09-18)",
        failed_rule="earnings_blackout",
    )
    autopsy = generate_autopsy(
        ticker="AAPL",
        decision=decision,
        candidate=_candidate(),
        risk=risk,
        contracts=1,
        executed=False,
    )
    assert autopsy.decision == "SELL_PUT"
    assert autopsy.risk_gate_approved is False
    assert autopsy.executed is False
    assert autopsy.risk_gate_failed_rule == "earnings_blackout"
    assert any("Risk gate rejected" in x for x in autopsy.contradicting_factors)
    assert autopsy.supporting_factors  # still keeps agent supports
    data = autopsy.to_dict()
    for key in (
        "supporting_factors",
        "contradicting_factors",
        "risk_gate_approved",
        "risk_gate_reason",
        "reasoning",
    ):
        assert key in data

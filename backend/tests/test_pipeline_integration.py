"""Integration-style tests with mocked market/agent pieces."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from options import OptionContract, PutCandidate
from pipeline import DecisionPipeline
from risk_engine import RiskGate
from technical import SupportLevel
from trade_autopsy import AgentDecision


def _history(n: int = 60) -> pd.DataFrame:
    close = np.linspace(100, 110, n)
    return pd.DataFrame(
        {
            "Open": close,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": np.full(n, 2_000_000),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="B"),
    )


def _candidate(expiry: str, strike: float = 40.0) -> PutCandidate:
    c = OptionContract(
        symbol="TEST",
        underlying="TEST",
        strike=strike,
        expiry=expiry,
        option_type="put",
        bid=2.4,
        ask=2.6,
        mid=2.5,
        iv=0.4,
    )
    return PutCandidate(
        contract=c,
        iv_rank=55.0,
        support=SupportLevel(40.0, "test", 0.7),
        spot=45.0,
        premium_dollars_per_contract=250.0,
        max_loss_per_contract=strike * 100,
        reasons=["test"],
    )


@pytest.mark.asyncio
async def test_avoid_does_not_execute(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path}/t.db"
    pipe = DecisionPipeline(
        session_factory=__import__("db.schema", fromlist=["init_db"]).init_db(db_url),
        risk_gate=RiskGate(),
        dry_run_orders=True,
        use_gemini=False,
    )
    expiry = (date.today() + timedelta(days=21)).isoformat()
    cand = _candidate(expiry)

    class FakeSignals:
        rsi = 50.0
        momentum_5d = 0.01
        volume_ratio = 1.0
        volatility_20d = 0.02
        last_close = 45.0
        history = _history()

        def to_dict(self):
            return {
                "ticker": "TEST",
                "last_close": 45.0,
                "rsi": 50.0,
                "momentum_5d": 0.01,
                "volume_ratio": 1.0,
                "volatility_20d": 0.02,
            }

    with (
        patch("pipeline.latest_signals", return_value=FakeSignals()),
        patch("pipeline.fetch_option_chain", return_value=[cand.contract]),
        patch("pipeline.select_candidate_puts", return_value=cand),
        patch("pipeline.check_earnings_date", return_value=None),
        patch(
            "pipeline.analyze_candidate",
            return_value=AgentDecision(
                decision="AVOID",
                confidence=0.2,
                reasoning="bad setup",
                supporting_factors=[],
                contradicting_factors=["low IV"],
            ),
        ),
        patch("pipeline.submit_cash_secured_put") as submit,
    ):
        autopsy = await pipe.analyze_ticker("TEST")
        submit.assert_not_called()
        assert autopsy.executed is False
        assert autopsy.decision == "AVOID"


@pytest.mark.asyncio
async def test_sell_put_requires_gate(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path}/t2.db"
    pipe = DecisionPipeline(
        session_factory=__import__("db.schema", fromlist=["init_db"]).init_db(db_url),
        dry_run_orders=True,
        use_gemini=False,
    )
    expiry = (date.today() + timedelta(days=21)).isoformat()
    # High strike blows position capital limit
    cand = _candidate(expiry, strike=200.0)

    class FakeSignals:
        rsi = 50.0
        momentum_5d = 0.0
        volume_ratio = 1.0
        volatility_20d = 0.02
        last_close = 210.0
        history = _history()

        def to_dict(self):
            return {
                "ticker": "TEST",
                "last_close": 210.0,
                "rsi": 50.0,
                "momentum_5d": 0.0,
                "volume_ratio": 1.0,
                "volatility_20d": 0.02,
            }

    with (
        patch("pipeline.latest_signals", return_value=FakeSignals()),
        patch("pipeline.fetch_option_chain", return_value=[cand.contract]),
        patch("pipeline.select_candidate_puts", return_value=cand),
        patch("pipeline.check_earnings_date", return_value=None),
        patch(
            "pipeline.analyze_candidate",
            return_value=AgentDecision(
                decision="SELL_PUT",
                confidence=0.9,
                reasoning="looks great",
                supporting_factors=["premium"],
                contradicting_factors=[],
            ),
        ),
        patch("pipeline.submit_cash_secured_put") as submit,
    ):
        autopsy = await pipe.analyze_ticker("TEST")
        submit.assert_not_called()
        assert autopsy.decision == "SELL_PUT"
        assert autopsy.risk_gate_approved is False
        assert autopsy.executed is False
        assert any("Risk gate" in x for x in autopsy.contradicting_factors)

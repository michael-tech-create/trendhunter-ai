"""Unit tests for deterministic RiskGate rules."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from risk_engine import RiskGate


@pytest.fixture
def gate() -> RiskGate:
    return RiskGate(
        min_premium_ratio=0.125,
        max_position_capital=5000,
        max_portfolio_capital=50000,
        max_contracts_per_day=3,
    )


def test_premium_ratio_pass(gate: RiskGate) -> None:
    # $625 credit on $5000 max loss = 0.125
    ok, _ = gate.check_premium_ratio(premium=625.0, max_loss=5000.0)
    assert ok is True


def test_premium_ratio_fail(gate: RiskGate) -> None:
    ok, reason = gate.check_premium_ratio(premium=50.0, max_loss=5000.0)
    assert ok is False
    assert "below minimum" in reason


def test_position_capital_fail(gate: RiskGate) -> None:
    # strike 200 * 1 * 100 = 20000 > 5000
    ok, reason = gate.check_position_capital(strike=200.0, contracts=1)
    assert ok is False
    assert "Position capital" in reason


def test_position_capital_pass(gate: RiskGate) -> None:
    ok, _ = gate.check_position_capital(strike=45.0, contracts=1)
    assert ok is True


def test_portfolio_exposure(gate: RiskGate) -> None:
    ok, reason = gate.check_portfolio_exposure(open_capital=48000, new_capital=3000)
    assert ok is False
    assert "Portfolio capital" in reason


def test_earnings_blackout_inside_window(gate: RiskGate) -> None:
    expiry = date.today() + timedelta(days=14)
    earnings = date.today() + timedelta(days=7)
    ok, reason = gate.check_earnings_blackout(earnings, expiry)
    assert ok is False
    assert "Earnings" in reason


def test_earnings_on_expiry_day_rejects(gate: RiskGate) -> None:
    expiry = date.today() + timedelta(days=10)
    ok, _ = gate.check_earnings_blackout(expiry, expiry)
    assert ok is False


def test_earnings_after_expiry_ok(gate: RiskGate) -> None:
    expiry = date.today() + timedelta(days=10)
    earnings = expiry + timedelta(days=5)
    ok, _ = gate.check_earnings_blackout(earnings, expiry)
    assert ok is True


def test_earnings_none_ok(gate: RiskGate) -> None:
    ok, _ = gate.check_earnings_blackout(None, date.today() + timedelta(days=10))
    assert ok is True


def test_daily_contract_limit(gate: RiskGate) -> None:
    ok, reason = gate.check_daily_contract_limit(contracts_today=3, new_contracts=1)
    assert ok is False
    assert "Daily contracts" in reason


def test_evaluate_trade_all_pass(gate: RiskGate) -> None:
    # strike 40 → max loss 4000; premium 500 → ratio 0.125
    verdict = gate.evaluate_trade(
        premium=500.0,
        strike=40.0,
        contracts=1,
        expiry=(date.today() + timedelta(days=21)).isoformat(),
        earnings_date=(date.today() + timedelta(days=60)).isoformat(),
        open_portfolio_capital=0.0,
        contracts_today=0,
    )
    assert verdict.approved is True
    assert verdict.failed_rule is None


def test_evaluate_trade_earnings_blocks_even_if_premium_ok(gate: RiskGate) -> None:
    expiry = date.today() + timedelta(days=14)
    verdict = gate.evaluate_trade(
        premium=500.0,
        strike=40.0,
        contracts=1,
        expiry=expiry,
        earnings_date=date.today() + timedelta(days=3),
        open_portfolio_capital=0.0,
        contracts_today=0,
    )
    assert verdict.approved is False
    assert verdict.failed_rule == "earnings_blackout"

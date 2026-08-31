# Deterministic Risk Gate

The risk gate is the last hard stop before paper execution. Gemini cannot override it.

## Why these rules exist

- **Premium / max loss ≥ 0.125**: Small premium on large notional is skewed tail risk (e.g. $50 credit vs $5,000 max loss).
- **Position capital cap**: One name cannot dominate the book in a demo or paper account.
- **Portfolio capital cap**: Force waiting for closes before piling on risk.
- **Earnings blackout**: Event vol and gap risk inside the option window is the #1 reject reason—no exceptions.
- **Max contracts per day**: Prevents scan-loop overallocation.

## Suggested API

```python
class RiskGate:
    def __init__(
        self,
        min_premium_ratio: float = 0.125,
        max_position_capital: float = 5000,
        max_portfolio_capital: float = 50000,
        max_contracts_per_day: int = 3,
    ) -> None: ...

    def check_premium_ratio(self, premium: float, max_loss: float) -> tuple[bool, str]: ...
    def check_position_capital(self, strike: float, contracts: int) -> tuple[bool, str]: ...
    def check_portfolio_exposure(self, open_capital: float, new_capital: float) -> tuple[bool, str]: ...
    def check_earnings_blackout(self, earnings_date, expiry) -> tuple[bool, str]: ...
    def check_daily_contract_limit(self, contracts_today: int, new_contracts: int) -> tuple[bool, str]: ...

    def evaluate_trade(self, ...) -> tuple[bool, str]:
        """Run all checks; first failure wins. Return (approved, reason)."""
```

## Evaluate sketch

```python
# max_loss for short put ≈ strike * contracts * 100 (cash-secured notional)
max_loss = strike * contracts * 100
ratio = premium / max_loss if max_loss else 0.0
# premium should be total credit in dollars (per-share premium * 100 * contracts)

if earnings_date is not None and earnings_date <= expiry:
    return False, f"Earnings on {earnings_date} inside window (expiry {expiry})"
```

Use total dollar premium consistently (document the convention in code). Prefer rejecting on ambiguous earnings dates rather than assuming clear.

## Autopsy coupling

Always persist:
- `risk_gate_approved: bool`
- `risk_gate_reason: str`

If agent says `SELL_PUT` and gate rejects, decision recorded as rejected execution with contradicting factor from the gate reason—not silent drop.

## Tests to include

- Each rule fails independently with expected message
- All rules pass → approved
- Earnings on expiry day → reject
- Ratio exactly at 0.125 → pass; just below → fail
- Portfolio at limit + new position → reject

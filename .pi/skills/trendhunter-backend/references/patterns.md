# Key Implementation Patterns

## CLI wrapper with retries

```python
def call_alpaca_cli(args: list[str], retries: int = 3) -> dict:
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["alpaca", *args],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            return json.loads(result.stdout)
        except (subprocess.CalledProcessError, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
            if attempt >= retries - 1:
                logging.exception("Alpaca CLI failed after retries: %s", e)
                raise
            time.sleep(2 ** attempt)
```

Never use bare `print` for errors—log and re-raise or return a structured error to the scan loop.

## Execution (CSP)

Submit only after `decision == SELL_PUT` **and** `risk_gate.evaluate_trade(...)[0]`.
Parse order id/status; on failure, autopsy records execution error and no phantom fill.

## Trade autopsy

```python
@dataclass
class TradeAutopsy:
    ticker: str
    decision: str
    confidence: float
    strike: float
    expiry: str
    premium: float
    breakeven: float
    max_loss: float
    iv_rank: float
    risk_level: str  # Low | Medium | High
    supporting_factors: list[str]
    contradicting_factors: list[str]
    position_size: dict
    invalidation_criteria: list[str]
    risk_gate_approved: bool
    risk_gate_reason: str
```

Example AVOID narrative judges should be able to read without code:

```
Decision: AVOID
Reasoning: Attractive headline premium but IV rank 18th percentile (cheap vol),
earnings three days before expiry, and premium/max-loss below 0.125 once event risk is considered.
Supporting: ["Strike 5% below spot", "Reasonable bid-ask"]
Contradicting: ["Earnings inside window", "Low IV rank", "Ratio below threshold"]
```

## WebSocket broadcast

```python
await manager.broadcast({
    "type": "risk_gate_result",
    "timestamp": datetime.utcnow().isoformat(),
    "ticker": ticker,
    "approved": approved,
    "reason": reason,
})
```

Broadcast at every pipeline stage so the demo UI never looks idle during long Gemini/CLI calls.

## Scan orchestration order

1. signal_fetched  
2. option/candidate selected  
3. agent_thinking → Decision  
4. risk_gate_result  
5. trade_executed **or** rejection path  
6. trade_autopsy (always)  
7. pnl_update (end of cycle)

## Config

Centralize watchlist, risk limits, model name, and paper flags in `config.py` + env.
Ship `.env.example` without secrets.

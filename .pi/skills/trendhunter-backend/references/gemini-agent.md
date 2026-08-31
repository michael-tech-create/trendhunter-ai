# Gemini Agent

## System prompt (use as foundation)

```
You are TrendHunter AI, an autonomous options-selling agent. Your core mission is NOT to find every possible trade.
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
Explanations must be clear, concise, and backed by tools you called.
```

## Required tools

| Tool | Purpose |
|------|---------|
| `get_option_chain(ticker, expiry)` | Strikes, premium, IV, bid/ask, Greeks |
| `check_earnings_date(ticker)` | Earnings date or null; compare to window |
| `analyze_support_level(ticker)` | Support price + confidence |
| `calculate_iv_percentile(ticker)` | IV rank 0–100 |
| `assess_volume_liquidity(bid, ask, mid)` | Liquid vs illiquid with reason |

Define tools as JSON schemas Gemini can call. Names must match implementations.

## Decision model

```python
class Decision(BaseModel):
    decision: str  # SELL_PUT | WAIT | AVOID
    confidence: float  # 0.0–1.0
    reasoning: str
    supporting_factors: list[str]
    contradicting_factors: list[str]
```

## Loop expectations

1. Present candidate (ticker, expiry, strike, market context).
2. Let the model call tools before deciding.
3. Parse into `Decision`; never skip risk gate after `SELL_PUT`.
4. Fold tool findings into autopsy supporting/contradicting lists.

## Debugging: model not calling tools

- System prompt must instruct tool use for contradiction checks
- Validate tool JSON schemas
- Align tool names with handlers
- Smoke-test with a simpler single-tool prompt

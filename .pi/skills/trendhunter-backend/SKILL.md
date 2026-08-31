---
name: trendhunter-backend
description: >
  Build, extend, and debug the TrendHunter AI Python backend—the FastAPI decision
  engine for an autonomous cash-secured-put options agent (Alpaca paper trading +
  Gemini reasoning + deterministic risk gate). Use whenever the user works on
  TrendHunter backend code, risk rules, Trade Autopsy, Alpaca CLI wrappers,
  WebSocket streaming, signals/options modules, agent tool-calling, P&L tracking,
  SQLite models, scan loops, or hackathon demo polish—even if they only name a
  single file (risk_engine.py, agent.py, execution.py) or say "fix the put
  pipeline," "why did risk reject this," or "stream autopsies to the dashboard."
compatibility: Python 3.11+, FastAPI, Uvicorn, Google Gemini API, Alpaca CLI, yfinance, pandas, numpy, ta, SQLAlchemy (SQLite), httpx, python-dotenv
---

# TrendHunter AI Backend

Build the decision engine for **TrendHunter AI**: an autonomous options-selling
agent for the Alpaca AI Trading Agents Hackathon.

## Central thesis

Do **not** build an AI that sells premium everywhere. Build an AI that knows when
the premium is not worth the risk.

Cash-secured puts only. Covered calls and multi-leg strategies are out of scope
for the 7-day build—one fully explained single-leg path beats a half-working
multi-strategy system in a live judged demo.

## 5-layer pipeline (inviolable)

1. **Market & options data** — RSI, momentum, volatility; chains with IV rank, strikes, premium
2. **Gemini agent reasoning** — tool calling to **challenge** the thesis (hunt reasons NOT to sell)
3. **Deterministic risk gate** — hard rules the AI cannot override
4. **Execution** — Alpaca CLI paper trading, or record rejection
5. **Trade Autopsy** — structured explainability; stream every step to the React dashboard via WebSocket

If Gemini says `SELL_PUT`, the risk gate still must approve. The risk gate always wins.

## When you start a task

1. Inspect existing `backend/` layout before inventing new structure.
2. Match the phase and module boundaries in `references/phases.md` and `references/file-layout.md`.
3. Keep business logic out of routes: risk rules stay in `risk_engine.py`, CLI in `cli_wrapper.py` / `execution.py`, Gemini in `agent.py`.
4. Prefer Pydantic/dataclasses, type hints, and `logging` (no `print()`).
5. Comment the *why* on non-obvious risk and decision code.

## Design principles (non-negotiable)

### Risk gate is hard
Deterministic only. Examples of auto-reject with no AI override:
- Earnings announcement inside the option window
- Premium-to-max-loss ratio below **0.125** (1:8)
- Position or portfolio capital over limits
- Max contracts-per-day exceeded

Default gate knobs (override only via config, never ad hoc in call sites):

| Rule | Default |
|------|---------|
| Min premium / max loss | 0.125 |
| Max capital per position | $5,000 |
| Max portfolio capital | $50,000 |
| Max contracts per scan day | 3 |

### Challenge the thesis
Gemini’s job is skepticism, not sales. Encourage tool use for earnings, support,
IV rank, and liquidity. `AVOID` and `WAIT` are successful outcomes—do not force
`SELL_PUT` because premium looks rich.

### Explainability first
Every analysis yields a `TradeAutopsy` with supporting and contradicting factors.
No black-box scores. A judge reading one autopsy must know exactly why the agent
acted or refused.

### Execution is a tool
Alpaca CLI is the only execution channel. Parse JSON, timeout, retry with backoff,
never assume success. Paper trading is required.

### Streaming is live
WebSocket every decision point: ticker scanned → signals → chain → agent thinking
→ risk gate → execute/reject → autopsy → P&L. Real-time feedback is part of the demo.

## Target module map

```
backend/
├── main.py              # FastAPI routes + WebSocket
├── config.py            # Settings/constants (no committed secrets)
├── agent.py             # Gemini + tools + Decision
├── risk_engine.py       # RiskGate hard rules
├── signals.py           # RSI, momentum, volume, HV
├── options.py           # Chains, IV rank, candidate puts
├── technical.py         # Support/resistance
├── execution.py         # Order submit via CLI
├── trade_autopsy.py     # Structured autopsy
├── pnl.py               # Portfolio P&L
├── cli_wrapper.py       # subprocess → alpaca → JSON
├── db/models.py, schema.py
└── tests/test_*.py
```

Details and phase checklists: `references/phases.md`, `references/file-layout.md`.

## Decision and autopsy shapes

```text
Decision: SELL_PUT | WAIT | AVOID
confidence: 0.0–1.0
reasoning: plain language, tool-backed
supporting_factors: [...]
contradicting_factors: [...]
```

```text
TradeAutopsy: ticker, decision, confidence, strike, expiry, premium,
breakeven, max_loss, iv_rank, risk_level, supporting_factors,
contradicting_factors, position_size, invalidation_criteria,
risk_gate_approved, risk_gate_reason
```

Gemini system prompt and tool list: `references/gemini-agent.md`.  
Risk gate implementation notes: `references/risk-gate.md`.  
Patterns (CLI retries, WS broadcast, autopsy): `references/patterns.md`.  
Debug playbook + test checklist: `references/testing-and-debug.md`.

## Coding expectations

- One responsibility per module; no monoliths.
- Heavy comments on risk and decision branches explaining *why* the rule exists.
- Type hints on all public functions.
- Log INFO at decision points; DEBUG for payloads.
- Unit-test risk rules and signals in isolation; integration-test the loop with mocked Gemini + CLI.
- If asked for both a feature and a reckless bypass of the risk gate, implement the feature and keep the gate hard.

## Hackathon constraints

- Options **paper** trading only (fresh paper account).
- Cash-secured puts only.
- Runnable submission using Alpaca Trading API / MCP / CLI.
- Live demo must show SCAN → ANALYZE → DECIDE → EXECUTE/REJECT with clear autopsies.

## Common failure modes to avoid

1. Trading on premium alone  
2. Soft-pedaling earnings blackouts  
3. Weak or AI-overridable risk gate  
4. Vague autopsies  
5. No end-to-end mocked tests before live paper  
6. Naive CLI calls without retries/fallback  

## How to respond to typical asks

| User ask | Approach |
|----------|----------|
| “Build risk engine” | `RiskGate` with separate check methods + unit tests; see `references/risk-gate.md` |
| “Wire Gemini” | Tools + skeptical system prompt + `Decision` model; see `references/gemini-agent.md` |
| “Add scan endpoint” | Orchestrate full pipeline in service functions; broadcast WS events from `main.py` |
| “Why no trade?” | Trace agent decision + each risk rule; ensure autopsy records both |
| “Demo polish” | Short watchlist, cache fallbacks, structured logs, `demo.py` under ~1 min |

Load the relevant `references/*.md` file before implementing that area. Prefer extending existing modules over creating parallel ones.

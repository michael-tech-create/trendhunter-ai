# Build Phases (7-Day Plan)

Use the phase that matches the current task. Do not skip risk gate or autopsy work to chase extra strategies.

## Phase 1 — Project setup & market signals

**Goal**: Bootstrap project, Alpaca auth, baseline signals.

- Structure: `backend/`, config, requirements, `.env.example` (never commit `.env`)
- Verify CLI: `alpaca` profile/login and sample option data calls
- `signals.py`: RSI(14), 5d momentum, volume/avg20, 20d historical vol via yfinance + `ta`

```python
def fetch_market_data(ticker: str, days: int = 60) -> pd.DataFrame:
    df = yf.download(ticker, period=f"{days}d", progress=False)
    df["rsi"] = RSIIndicator(df["Close"], window=14).rsi()
    df["momentum_5d"] = (df["Close"] - df["Close"].shift(5)) / df["Close"].shift(5)
    df["volume_ratio"] = df["Volume"] / df["Volume"].rolling(20).mean()
    df["volatility_20d"] = df["Close"].rolling(20).std() / df["Close"].rolling(20).mean()
    return df
```

## Phase 2 — Options data & candidates

- `cli_wrapper.py`: subprocess to Alpaca CLI, JSON parse, errors
- `options.py`: chain fetch, IV rank vs ~252d history, candidate CSPs, liquidity filter (bid-ask < ~5% of mid)
- `technical.py`: support (20d low / pivots / MA50); strike at or slightly below support with cushion

```python
def calculate_iv_rank(current_iv: float, iv_history: list[float]) -> float:
    if not iv_history:
        return 50.0
    below = sum(1 for iv in iv_history if iv < current_iv)
    return (below / len(iv_history)) * 100
```

## Phase 3 — Gemini agent reasoning

- `agent.py`: client, system prompt (see `gemini-agent.md`), tools, parse to `Decision`
- Tools must enable contradiction-hunting, not confirmation bias
- Decisions: `SELL_PUT` (0.7–1.0), `WAIT` (0.4–0.7), `AVOID` (0.0–0.4)

## Phase 4 — Deterministic risk engine + autopsy + schema

- `risk_engine.py`: ratio, position capital, portfolio capital, earnings blackout, max contracts/day
- `trade_autopsy.py`: full structured object for DB + UI
- DB tables: signals, option_snapshots, trades, autopsies, portfolio

See `risk-gate.md`.

## Phase 5 — Execution, DB models, P&L, main loop

- `execution.py`: submit CSP via CLI; parse order id/status; handle BP/invalid strike
- `db/models.py`: SQLAlchemy models
- `pnl.py`: realized/unrealized, capital deployed, premium collected
- Loop: signals → chain → candidates → Gemini → risk gate → execute only if both approve → always autopsy

## Phase 6 — FastAPI + WebSocket

Routes: `POST /scan`, `GET /trades`, `GET /portfolio`, `GET /watchlist`, `WS /ws`

Emit: `signal_fetched`, `agent_thinking`, `risk_gate_result`, `trade_executed`, `trade_autopsy`, `pnl_update`, `error`

CORS for React dev origin (e.g. `http://localhost:5173`).

## Phase 7 — E2E tests & demo polish

- Integration tests with mocked Gemini + CLI
- JSON cache fallbacks for demo resilience
- CLI retries (3x, exponential backoff)
- `demo.py`: 1–2 tickers, full pipeline under ~1 minute
- Structured logging of every decision point

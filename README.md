TrendHunter backend is up. Live demo confirmed the core story: the agent can want the trade; the risk gate still blocks it when the numbers do not justify it.

What's built

```
backend/
├── main.py              # FastAPI + WebSocket (/scan, /trades, /portfolio, /ws)
├── pipeline.py          # Full 5-layer orchestration
├── config.py            # Settings + risk defaults
├── signals.py           # RSI, momentum, volume, HV
├── technical.py         # Support levels + strike targeting
├── options.py           # Chain fetch (Alpaca CLI, yfinance fallback), IV rank, CSP pick
├── cli_wrapper.py       # Alpaca CLI + retries
├── agent.py             # Gemini reasoning, with a skeptical heuristic fallback
├── earnings.py          # Earnings blackout input
├── risk_engine.py       # Hard RiskGate (no AI override)
├── trade_autopsy.py     # Structured explainability
├── execution.py         # CSP paper orders, live on Alpaca's paper trading account
├── pnl.py               # Portfolio snapshot
├── demo.py              # Fast CLI demo
├── db/models.py + schema.py
└── tests/               # 16 passing
```

Verified behavior

- 16/16 tests pass.
- Live demo.py AAPL: heuristic said SELL_PUT, gate rejected it (premium_ratio + capital). The autopsy recorded both sides, no order was placed.
- Same pattern on F: capital was fine, but a skinny premium still got blocked.
- Alpaca CLI integration is fixed and verified. `options.py` fetches real option chains via `alpaca data option chain`, parses OCC contract symbols correctly, and returns real strikes, expiries, and bid/ask pricing.
- Real paper execution is confirmed. `execution.py` submitted a live cash-secured put (AAPL, strike 322.5, expiry 2026-09-18) that Alpaca accepted, using a real OCC symbol, correct CLI flags, and a client order id to prevent duplicate submissions on retry. Market orders are rejected outside trading hours; limit orders are not, and are now the default.
- Gemini reasoning is fixed and verified. The agent makes a real API call, not just the heuristic fallback, and produces grounded, specific AVOID/WAIT/SELL_PUT decisions with real supporting and contradicting factors.

That matches the thesis: premium alone never forces a trade, whether the reasoning behind that call comes from the heuristic fallback or from Gemini itself.

Run it
=======
# TrendHunter AI

Autonomous cash-secured put agent: **Gemini challenges the trade**, a **deterministic risk gate** can still block it, and paper execution goes through the **Alpaca CLI**.

## Backend

**[backend/README.md](backend/README.md)** for setup, data sources, Alpaca/Gemini auth, and a verified `python3 demo.py F` walkthrough.

```bash
cd backend
source .venv/bin/activate


python demo.py AAPL F          # runs Gemini when configured, falls back to heuristic if not
uvicorn main:app --reload --port 8000
# POST /scan   WS /ws   GET /trades   GET /portfolio
```

Copy backend/.env.example to .env and set the following:

- GEMINI_API_KEY: your key. Make sure the line has no trailing newline and no duplicate or export-prefixed copy of the same variable; a malformed .env caused a hard-to-diagnose httpx header error for one of us today.
- GEMINI_MODEL=gemini-3.6-flash: the code's built-in default (gemini-2.0-flash) is deprecated and will fail with a 404. Set this explicitly until config.py's default is updated.

Install and authenticate the Alpaca CLI (`alpaca profile login`) to move off dry-run. Once authenticated, `data option chain`/`snapshot` reliably return zero for all greeks fields in the paper environment, confirmed empirically across multiple tickers and expiries, not just near-expiry contracts. Strike selection should not depend on delta from the CLI; it currently does not, and should stay that way.

Sensible next steps

1. Update config.py's default GEMINI_MODEL to gemini-3.6-flash so a fresh clone does not repeat today's 404.
2. Wire real Gemini tool-calling (live tool calls, not a single JSON completion over pre-fetched context).
3. Run pipeline.py on a schedule (cron or a simple loop) so decision and P&L history accumulates across the full competition window, not just on demand.
4. Tune the watchlist and capital limits for names that can clear the 0.125 premium/max-loss floor in paper.
5. Build the React dashboard against /ws, including a P&L view over time.



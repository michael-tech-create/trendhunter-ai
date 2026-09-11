# TrendHunter AI Backend

Autonomous **cash-secured put (CSP)** agent for the Alpaca AI Trading Agents Hackathon.

**Thesis:** Do not sell premium everywhere. Know when the premium is not worth the risk.

A successful demo does **not** mean an order was placed. Gemini can `AVOID` / `WAIT`, and the deterministic risk gate can still reject a trade the agent likes. That dual veto is intentional.

## Pipeline

1. **Market signals** — OHLCV via yfinance → RSI, 5d momentum, volume ratio, 20d volatility (`signals.py`)
2. **Option chain** — Alpaca CLI first; yfinance fallback (`options.py`, `cli_wrapper.py`)
3. **Technical strike targeting** — support level + OTM put selection (`technical.py`)
4. **Gemini agent** — challenges the CSP thesis; heuristic fallback if Gemini fails (`agent.py`)
5. **Risk gate** — hard rules AI cannot override (`risk_engine.py`)
6. **Execution** — Alpaca CLI paper CSP (demo stays dry-run) (`execution.py`)
7. **Trade Autopsy** — structured explainability + optional WebSocket stream (`trade_autopsy.py`, `main.py`)

## Data sources

| Data | Source | Notes |
|------|--------|--------|
| Stock OHLCV / RSI / momentum / volume | **yfinance** | Not Alpaca |
| Earnings date | **yfinance** | Used for blackout checks |
| Option chain quotes | **Alpaca CLI** (`alpaca data option chain`) | Falls back to yfinance if CLI/auth fails |
| Paper orders | **Alpaca CLI** (`alpaca order submit`) | Demo uses `dry_run_orders=True` |
| Agent reasoning | **Gemini** (`GEMINI_API_KEY`) | Falls back to heuristic |

Python does **not** call the Alpaca Trading REST API directly. It shells out to the `alpaca` CLI. Keys from `.env` are injected into that subprocess by `cli_wrapper.py`.

Use **Trading API paper keys** (`PK…`) and `https://paper-api.alpaca.markets`.  
Do **not** use Broker sandbox keys (`CK…` / `broker-api.sandbox…`) — those cause `401 unauthorized`.

## Setup

### 1. Python env

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in keys
```

### 2. `.env` (required keys)

```env
GEMINI_API_KEY=AQ....                 # or your Google AI key
GEMINI_MODEL=gemini-3.6-flash         # or gemini-2.0-flash

ALPACA_API_KEY=PK................     # Trading API paper key
ALPACA_SECRET_KEY=................
ALPACA_BASE_URL=https://paper-api.alpaca.markets
ALPACA_CLI_PATH=alpaca                # or absolute path, e.g. /home/you/go/bin/alpaca
```

Tips:

- Prefer a clean shell: `unset GEMINI_API_KEY ALPACA_API_KEY ALPACA_SECRET_KEY` so a polluted export does not override `.env`.
- Enable **options** on the Alpaca **paper** account (level 2+; level 3 is fine for CSPs).

### 3. Alpaca CLI (Go binary — project stays Python)

The CLI is a separate binary your Python code invokes. Install with Go (already common on Linux):

```bash
go install github.com/alpacahq/cli/cmd/alpaca@latest
echo 'export PATH="$HOME/go/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
alpaca version
```

Auth options:

```bash
# A) Profile login (stores credentials under ~/.config/alpaca/)
alpaca profile login --api-key    # paste PK... paper key + secret

# B) Or rely on .env PK keys (cli_wrapper injects them into the subprocess)
alpaca doctor
alpaca account get
```

`cli_wrapper.py` also prepends `~/go/bin` to `PATH` for child processes, so demo runs work even if you forget to export `PATH` in the shell.

## Quick start

```bash
cd backend
source .venv/bin/activate

# Full live path: Alpaca option chain + Gemini agent + risk gate (orders dry-run)
python3 demo.py F

# API + WebSocket
uvicorn main:app --reload --port 8000
# POST http://localhost:8000/scan
# WS   ws://localhost:8000/ws
```

`demo.py` uses `use_gemini=True` and `dry_run_orders=True`.

Prefer liquid, lower-priced names (e.g. `F`) for demos. Expensive underlyings like `AAPL` often fail `max_position_capital` ($5,000) because one CSP needs `strike × 100` cash.

## Example run (`python3 demo.py F`)

Verified live path (abbreviated):

```text
signals     → F close=13.88 rsi=47.8 mom5=-1.84% …
options     → CLI chain F 2026-09-25: 26 contracts          # Alpaca, not yfinance
technical   → Support 13.15 …
candidate   → strike=13.5 mid=0.20 iv_rank≈80
agent       → Gemini decision AVOID conf=0.20
risk_engine → reject premium_ratio (0.015 < 0.125)
execution   → skipped (executed=false)
```

Autopsy highlights from that run:

| Field | Value |
|-------|--------|
| Decision | `AVOID` |
| Strike / expiry | `$13.50` / `2026-09-25` |
| Premium / max loss | `$20` / `$1,350` → ratio **0.015** |
| IV rank | ~80th percentile |
| Bid / ask | `0.18` / `0.22` (spread **20%**) |
| Risk gate | Failed `premium_ratio` (min **0.125**) |
| Order | Not sent |

Gemini rejected the setup (strike above support, skinny yield, wide spread). The risk gate independently blocked the same weak premium/max-loss ratio. That is the product working as designed.

## Risk defaults

| Rule | Default |
|------|---------|
| Min premium / max loss | 0.125 (1:8) |
| Max capital / position | $5,000 |
| Max portfolio capital | $50,000 |
| Max contracts / day | 3 |
| Earnings inside option window | auto-reject |

Configured in `config.py` / `.env`.

## Project layout

```text
backend/
├── main.py           # FastAPI + WebSocket
├── demo.py           # CLI demo loop
├── pipeline.py       # 5-layer orchestration
├── config.py         # Settings + risk defaults
├── signals.py        # yfinance market signals
├── technical.py      # Support + strike targeting
├── options.py        # Chain fetch, IV rank, CSP pick
├── cli_wrapper.py    # Alpaca CLI subprocess + .env key injection
├── agent.py          # Gemini + heuristic fallback
├── earnings.py       # Earnings helper
├── risk_engine.py    # Hard RiskGate
├── trade_autopsy.py  # Explainability payload
├── execution.py      # Paper CSP orders
├── pnl.py            # Portfolio snapshot
├── db/               # SQLite models
└── tests/
```

## Tests

```bash
cd backend
source .venv/bin/activate
pytest -q
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No module named 'pydantic'` | Activate `.venv` before `python3 demo.py` |
| `Alpaca CLI not found` | Install CLI; ensure `~/go/bin` on `PATH` or set `ALPACA_CLI_PATH` |
| `authentication required` / `401` | Use `PK…` paper keys (not `CK…`); `unset` old exports; re-check `.env` |
| `yfinance chain` in logs | CLI failed; auth/PATH issue — see above |
| `Heuristic decision` instead of Gemini | Missing/invalid `GEMINI_API_KEY`, or shell override — `unset GEMINI_API_KEY` |
| Gate rejects every name | Expected when premium/max-loss &lt; 0.125 or capital &gt; $5k |

## Notes

- Covered calls / multi-leg strategies are out of scope.
- Demo orders stay **dry-run** even when the CLI is authenticated.
- Without Gemini, the heuristic agent still emits `SELL_PUT` / `WAIT` / `AVOID` so the pipeline remains demoable offline.

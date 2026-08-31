# TrendHunter AI Backend

Autonomous **cash-secured put** agent for the Alpaca AI Trading Agents Hackathon.

**Thesis:** Do not sell premium everywhere. Know when the premium is not worth the risk.

## Pipeline

1. Market & options data (`signals.py`, `options.py`, `technical.py`)
2. Gemini (or heuristic) agent — challenges the thesis (`agent.py`)
3. Deterministic risk gate — AI cannot override (`risk_engine.py`)
4. Execution via Alpaca CLI paper trading (`execution.py`)
5. Trade Autopsy + WebSocket stream (`trade_autopsy.py`, `main.py`)

## Quick start

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add GEMINI_API_KEY if available

# Offline demo (heuristic agent, dry-run orders)
python demo.py AAPL MSFT

# API + WebSocket
uvicorn main:app --reload --port 8000
# POST http://localhost:8000/scan
# WS   ws://localhost:8000/ws
```

## Tests

```bash
cd backend
pytest -q
```

## Risk defaults

| Rule | Default |
|------|---------|
| Min premium / max loss | 0.125 (1:8) |
| Max capital / position | $5,000 |
| Max portfolio capital | $50,000 |
| Max contracts / day | 3 |
| Earnings in window | auto-reject |

## Notes

- Covered calls / multi-leg are out of scope.
- Orders default to **dry_run** until Alpaca CLI is installed and authenticated.
- Without `GEMINI_API_KEY`, the heuristic agent still produces SELL_PUT / WAIT / AVOID.

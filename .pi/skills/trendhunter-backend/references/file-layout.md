# File Layout by Phase

## After Phase 1
```
backend/
├── main.py
├── config.py
├── signals.py
├── requirements.txt
├── .env.example
└── README.md
```

## After Phase 2
Add: `cli_wrapper.py`, `options.py`, `technical.py`

## After Phase 3
Add: `agent.py`

## After Phase 4
Add: `risk_engine.py`, `trade_autopsy.py`, `db/__init__.py`, `db/schema.py`

## After Phase 5
Add: `execution.py`, `pnl.py`, `db/models.py`

## After Phase 6
Update `main.py` (routes + WS); optional `connection_manager.py`

## After Phase 7
Add: `log_config.py`, `demo.py`, `tests/`, `data/cache.json`

## Separation of concerns

| Module | Owns | Does not own |
|--------|------|----------------|
| `signals.py` | OHLCV-derived indicators | Orders, risk |
| `options.py` | Chain/IV/candidates | Gemini prompts |
| `technical.py` | Support/resistance | Execution |
| `agent.py` | Gemini + Decision | Hard risk overrides |
| `risk_engine.py` | Deterministic approve/reject | Soft AI scoring |
| `execution.py` | CLI order submit/parse | Strategy choice |
| `trade_autopsy.py` | Explainability payload | Side-effecting orders |
| `main.py` | HTTP/WS orchestration | Embedded risk math |
| `cli_wrapper.py` | Subprocess + retries | Business rules |

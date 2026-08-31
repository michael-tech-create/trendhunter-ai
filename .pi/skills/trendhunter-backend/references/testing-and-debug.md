# Testing & Debugging

## Unit tests

- [ ] Risk gate: each rule in isolation (ratio, capital, earnings, daily cap)
- [ ] Signals: known OHLCV → expected RSI/momentum band
- [ ] CLI wrapper: mocked subprocess, retries, timeout, bad JSON
- [ ] Autopsy: required fields present and serializable

## Integration tests

- [ ] Full loop with mocked Gemini + mocked CLI
- [ ] `SELL_PUT` executes only if agent **and** gate approve
- [ ] `AVOID` / `WAIT` logged, no order
- [ ] Gate reject after `SELL_PUT` → no order, autopsy explains gate
- [ ] Autopsy always written

## Manual / demo

- [ ] 1–2 ticker scan for speed
- [ ] Console/logs show all decision points
- [ ] DB has trades, autopsies, P&L snapshot
- [ ] React WS receives ordered events
- [ ] Forced gate failure → zero orders

## Debug playbook

| Symptom | Checks |
|---------|--------|
| Gemini not calling tools | Prompt, schemas, name mismatch, simplify prompt |
| CLI timeout | `alpaca --version`, `alpaca account get`, network, backoff + cache |
| Gate blocks everything | Log each ratio/capital number; thresholds in config; synthetic fixtures |
| WS silent in UI | CORS, WS URL, `await broadcast`, browser Network → WS |
| Unclear autopsy | Require supporting + contradicting lists; include gate reason |

## Post-hackathon (only if asked)

Postgres, auth on routes, rate-limit `/scan`, alerts on large risk events, env-specific config, external monitoring.

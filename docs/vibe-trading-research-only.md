# Vibe-Trading research-only import

The adapter in `scripts/import_vibe_trading_research.py` imports an existing
HKUDS/Vibe-Trading backtest run directory into a Stock Razor evidence envelope.
It reads `config.json`, `run_card.json`, and optional `artifacts/equity.csv`,
`artifacts/trades.csv`, and `artifacts/metrics.csv`. It does not start the Vibe
MCP server, fetch data, call paid providers, or place orders.

```powershell
python scripts/import_vibe_trading_research.py C:\path\to\vibe-run --write work\vibe-import.json
```

The result is always `RESEARCH_ONLY`; `radar_admission` is `BLOCKED` and
`trade_execution` is `NO`. Missing provider finality, timezone/calendar proof,
explicit execution friction, or a governed OOS declaration remains
`UNKNOWN`/`NOT_VERIFIED`. The importer does not infer these facts from HTTP
success, a run card, or the presence of CSV files.

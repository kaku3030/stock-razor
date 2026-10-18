# Vibe-Trading research-only import

The adapter in `scripts/import_vibe_trading_research.py` imports local
HKUDS/Vibe-Trading run artifacts. It does not start Vibe-Trading, fetch market
data, call paid providers, or place orders.

The result is always `RESEARCH_ONLY`; `radar_admission` is `BLOCKED` and
`trade_execution` is `NO`. OOS requires a governed holdout object with a
dataset hash and an explicit no-tuning assertion. Cost validation requires
finite, non-negative `commission_bps` and `slippage_bps` values. Declarations
alone remain `NOT_VERIFIED`/`UNKNOWN`.

## Replay Lab execution

```powershell
python scripts/vibe_trading_research.py "compare B0, V0.2, and Strong Pullback in Replay Lab" `
  --fixture tests/fixtures/strategy_lab/aapl_getdata_12h_recorded_fixture_v1.json `
  --write work/vibe-replay-report.json
```

The command runs the offline OHLC Replay Lab against an existing immutable
fixture. It compares `B0`, `V0.2`, and `Strong Pullback`, reports gross and
explicit 0/1/2/5 bps-per-side cost scenarios, and separates six training rows
from a two-row governed holdout. The holdout is hashed and marked
`strategy_not_tuned_on_holdout=true`; the small fixture is also marked
`statistical_power=INSUFFICIENT_SMALL_FIXTURE`.

Without `--fixture`, the natural-language entry remains a request with
`execution=NOT_RUN`. Every completed report remains `RESEARCH_ONLY`, with
`radar_admission=BLOCKED`, `trade_execution=NO`, and no provider, MCP, paper,
or trading path. The CLI also emits `report_sha256`, calculated over the
canonical report before that field is added.

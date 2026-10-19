# Vibe-Trading research-only import

The adapter in `scripts/import_vibe_trading_research.py` imports local
HKUDS/Vibe-Trading run artifacts. It does not start Vibe-Trading, fetch market
data, call paid providers, or place orders.

The result is always `RESEARCH_ONLY`; `radar_admission` is `BLOCKED` and
`trade_execution` is `NO`. OOS requires a governed holdout object with a
dataset hash and an explicit no-tuning assertion. Cost validation requires
finite, non-negative `commission_bps` and `slippage_bps` values. Declarations
alone remain `NOT_VERIFIED`/`UNKNOWN`.

## Capturing a public historical sample

For a US daily research capture, `capture_research_eod.py --source yahoo_chart`
stores the raw Yahoo Chart response hash beside an audit-ready CSV. The capture
is still `CAPTURED_NOT_APPROVED`: Yahoo does not supply an independent provider
finality or bar-closure attestation, so Replay Lab keeps historical eligibility
`BLOCKED` until those fields are separately evidenced.

```powershell
python scripts/capture_research_eod.py --market us --source yahoo_chart `
  --symbol AAPL --start 2024-01-01 --end 2026-01-01 `
  --output work/AAPL_yahoo_daily_2024_2025.csv
python scripts/vibe_trading_research.py `
  "compare B0, V0.2, and Strong Pullback in Replay Lab" `
  --csv work/AAPL_yahoo_daily_2024_2025.csv `
  --write work/AAPL_yahoo_replay_report.json
```

The audit separates source-payload provenance, timezone/DST, XNYS session
membership, chronology, freshness, bar closure, and provider finality. A fresh
capture is not automatically eligible historical data.

## Replay Lab execution

```powershell
python scripts/vibe_trading_research.py "compare B0, V0.2, and Strong Pullback in Replay Lab" `
  --fixture tests/fixtures/strategy_lab/aapl_getdata_12h_recorded_fixture_v1.json `
  --write work/vibe-replay-report.json
```

The command runs the offline OHLC Replay Lab against an existing immutable
fixture. The first slice uses explicitly labelled exploratory proxy rules:
B0 holds from first open to final close, V0.2 buys after a prior up-close, and
Strong Pullback buys after two declining closes. These are not verified
canonical strategy specifications. The report marks
strategy_rule_contract=EXPLORATORY_PROXY_NOT_CANONICAL and
canonical_strategy_spec=NOT_VERIFIED. It reports gross and
explicit 0/1/2/5 bps-per-side cost scenarios, and separates six training rows
from a two-row diagnostic holdout. The
holdout is hash-bound but not claimed as validated out-of-sample evidence;
rule pre-registration is NOT_VERIFIED, and the sample is marked
statistical_power=INSUFFICIENT_SMALL_FIXTURE. Each strategy and cost scenario
now includes a per-bar equity curve, trade count, net return, and maximum
drawdown using bar-low/close mark-to-market. The strict walk-forward gate
records train/holdout hashes, chronological leakage status, and observed
sample counts; this fixture remains BLOCKED_INSUFFICIENT_SAMPLE.

Without `--fixture`, the natural-language entry remains a request with
`execution=NOT_RUN`. Every completed report remains `RESEARCH_ONLY`, with
`radar_admission=BLOCKED`, `trade_execution=NO`, and no provider, MCP, paper,
or trading path. The CLI also emits `report_sha256`, calculated over the
canonical report before that field is added.

Existing local CSV captures can be replayed without provider I/O:

```powershell
python scripts/vibe_trading_research.py "compare B0, V0.2, and Strong Pullback in Replay Lab" `
  --csv work/US_QQQ_5m.csv --csv work/US_NVDA_5m.csv --csv work/US_AMD_5m.csv `
  --write work/vibe-replay-multi-symbol-report.json
```

CSV inputs must contain strictly ordered `time_key`, `open`, `high`, `low`,
and `close` columns. The report records each source file hash and source
metadata. Provider finality remains `UNKNOWN`; unavailable requested symbols
must remain `NOT_VERIFIED` rather than being synthesized.

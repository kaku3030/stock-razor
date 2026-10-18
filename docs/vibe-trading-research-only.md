# Vibe-Trading research-only import

The adapter in `scripts/import_vibe_trading_research.py` imports local
HKUDS/Vibe-Trading run artifacts. It does not start Vibe-Trading, fetch market
data, call paid providers, or place orders.

The result is always `RESEARCH_ONLY`; `radar_admission` is `BLOCKED` and
`trade_execution` is `NO`. OOS requires a governed holdout object with a
dataset hash and an explicit no-tuning assertion. Cost validation requires
finite, non-negative `commission_bps` and `slippage_bps` values. Declarations
alone remain `NOT_VERIFIED`/`UNKNOWN`.

## Minimal research entry

```powershell
python scripts/vibe_trading_research.py "run Strong Pullback in Replay Lab"
```

Supported profiles are `B0`, `V0.2`, and `Strong Pullback`. This entry emits a
research request bound to the existing Strategy Lab replay engine with
`execution=NOT_RUN`; it does not claim a replay result without caller-supplied
events and governed validation evidence.

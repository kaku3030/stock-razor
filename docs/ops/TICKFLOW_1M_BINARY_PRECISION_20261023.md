# One-minute binary precision research subset

TickFlow support describes original JSON prices and the <=1e-5 vendor OHLC
rule. That broader same-day 1m rule remains unavailable before post-close.
The separate binary64 subset requires every raw OHLC price within eight ULPs
of its 0.001 CNY ETF tick, and a tick lattice enclosing the candle body.
Original values are preserved, never rounded or repaired in output. A 1e-9
CNY discrepancy is still quarantined. This distinguishes representation noise
from substantive price differences rather than accepting the full vendor bound.

Both writer and reader require the same check plus 90-second grace, full due
grid, numeric/volume/amount checks, and preserve NOT_VERIFIED finality,
UNPROVEN currentness, partial bars, record_only and BLOCKED admission.
Windows diagnostics mirror this exact subset; its former 1e-9 negative
regression remains unchanged. After-close behavior remains unchanged.

Two original-value normalization regressions fail on base9a649d2;137 related
checks pass after this change. Live quarantine coverage is a hypothesis until
collector deployment and independent complete20frame readback. Do not infer
full-day continuous PASS, dual-end parity or immutable finality from this fix.
Rollback: revert the change and redeploy the prior bounded research worker.

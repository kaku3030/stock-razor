# Isolating pre-existing manual SIM holdings from new Paper strategy deltas
2026-10-12 — **offline research / shadow review only**

The operator's US SIMULATE account already contains four manually initiated
LONG holdings predating STOCK RAZOR. The existing #588/#593/#598 policies
quarantine and compare the old portfolio, but a new strategy may eventually
trade the **same US ticker**. The pre-existing 1100 hypothetical units and a
new strategy purchase of two units must not be conflated with 1102 new units,
and a sale of old manually held shares must not be attributed to a strategy
with zero holdings.

This pure module checks that an explicitly reviewed, accepted legacy
snapshot plus **only** chronologically ordered candidate strategy deltas
matches a separately supplied current broker position snapshot. It requires
one explicit account identifier inside memory, a fresh current observation
<=120 seconds old, and bounded typed LONG-only positions and fill records.
Duplicate fill IDs/actions, invented extra broker positions, conflicting
accounts, unaudited old-holding sales, malformed/future/stale timestamps,
unsupported shorts, and zero/negative/NaN quantities fail closed.

## Important distinction

All inputs are *caller supplied*. A fill ID and a strategy_action_id cannot
alone prove the broker executed an independent fill; successful arithmetic
only returns **SHADOW_REVIEW_ONLY** with
provenance_status=NOT_INDEPENDENTLY_ATTESTED. A zero-fill match returns
LEGACY_BASELINE_ONLY. Both statuses keep independent_realized_fills_proven,
strategy_pnl_eligible, broker_mutation_allowed, paper_auto_ready and live_trade
FALSE and maintain RADAR/SOURCE_ARBITER blocked.

This module deliberately:
- does not ingest live OpenD, place or cancel orders, save account IDs,
  calculate or report any P&L, publish positions, or use paid providers;
- does not authorize a short strategy, partial fill aggregation, fills outside
  the observed session, or automatic order attribution to old holdings;
- does not attest session identity, independent broker provenance or accuracy
  of caller supplied snapshots.

Future acceptance must privately prove source/account/session and provider
readback provenance, plus broker-native independent fill identity, idempotency,
atomic order/cancel lifecycle, global kill switch, and data/risk admission.
An explicit operator consent is needed before the first SIMULATE order;
this PR is no such authorization.

PAPER_AUTO_READY=NO; RADAR_ADMISSION=BLOCKED;
SOURCE_ARBITER_ADMISSION=BLOCKED; LIVE_TRADE=NO.

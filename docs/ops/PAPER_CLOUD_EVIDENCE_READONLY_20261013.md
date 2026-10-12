# Cloud Paper evidence review: observation-only, 2026-10-13

Status: **SOURCE PR / SYNTHETIC TESTS ONLY**. This change does **not**
deploy a cloud Paper process, read an account, invoke a market-data provider,
send a notification, place a SIM order, or change a runtime gate.

## Why this slice exists

Offline Paper simulation already has the engine, durable journal, single-writer
orchestration, negative tests, eight same-store restarts and ninth recovery
(PR #627). AWS OpenD US SIM **read-only** account/funds/positions/orders/history
RPCs previously passed, but the observed account has pre-existing positions.
Those are quarantined legacy inventory, not new STOCK RAZOR simulated fills.

OpenD LiveFeed and Radar Worker have since been deployed to the same protected
source revision (Actions #38266825239 / #38267115978). The US exact source SHA
is **PASS**, but continuous quote timestamps, 15m/60m closed-grid evidence
remain **NOT_VERIFIED** (Actions #38267268628). The separately authorized
TickFlow Premium 30-second WS smoke received only initial cached candidates
without subsequent updates during A-share off-hours (Actions #38267425315).
Neither vendor is qualified for automatic Paper market-data binding.

## Read-only gate, no execution capability

`assess_cloud_paper_evidence` combines three **caller-supplied** objects:

1. Existing offline `ShadowReadinessResult`, requiring a read-only-shadow
   candidate and preserved BLOCKED source/Radar, NO live-trade flags.
2. Existing independent local-vs-AWS SIM `SimContinuityReview`: matching
   privately approved account, positions, and non-executable
   `MATCHED_FOR_REVIEW` status. Matching alone never establishes fills.
3. New `CloudPaperObservation` with explicit bool-or-UNKNOWN gates for:
   exact OpenD/Radar revisions, independently verified quote rights, sustained
   post-initial quote progression, timestamp freshness, closed 15m/60m bars,
   K5M volume/turnover parity, legacy position quarantine, cloud restart
   reconciliation, verified **phone receipt** of notifications, and an
   independent external SIM fill receipt.

Each missing value stays `_UNKNOWN`; explicit false stays `_FAILED`;
truthy non-boolean values are `_INVALID`. Output reasons have fixed safe
names only and cannot echo account IDs, position inventory or provider tokens.

Even if all *synthetic* gates are set to true, the maximum classification is
`EVIDENCE_READY_FOR_SUPERVISED_REVIEW`:
`paper_auto_ready=false`, `broker_mutation_allowed=false`,
`radar_admission=BLOCKED`, `source_arbiter_admission=BLOCKED`,
`live_trade=NO`, `trade_execution=NO`.

**This module is not a provider attestor or an execution admission gate.**
Real production evidence must have signed-off provenance, UTC sampling windows,
latency and immutable run IDs from actual AWS sources before the Main Control
may use it for *supervised planning*. Never fabricate true inputs or interpret
this output as permission to start automated or manual external SIM orders.

## Next separately validated actions

- **OpenD**: controlled live quote sequence + 15m/60m closure and K5M unit
  parity; independently prove quote rights with correct scope.
- **TickFlow**: one bounded active-A-share-session WS test verifying at least
  two provider timestamp advances *after* the initial snapshot, then session
  continuity and bar semantics; an off-session ACK does not qualify the feed.
- **Paper**: obtain up-to-date private Windows+AWS SIM account/position
  observations and the approved identity file for comparison, without copying
  account IDs or holdings to public Actions. Keep old positions quarantined.
  Independent SIM fill receipts remain unavailable under the existing moomoo
  OpenD SIM API; internal deterministic Paper stays a separate,
  correctly-labelled research environment. Validate cloud no-order
  restart/reconciliation and phone notification receipt independently.

Reference: `docs/PAPER_AUTO_ACCEPTANCE_MATRIX_V0_1.md`,
`docs/paper-acceptance-matrix-v02.md`.

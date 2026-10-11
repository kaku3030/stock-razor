# Paper Trading Acceptance Matrix V0.2

> Scope: controlled Paper progression only. This document does not authorize AWS deployment, paid market-data calls, external broker calls, notification sends, or live trading.

## Current baseline

| Layer | Current state | Evidence |
|---|---|---|
| Offline Paper runner | READY | PR #539, canonical reconcile → Shadow → Paper Engine path |
| Durable execution/shadow stores | IMPLEMENTED | Separate SQLite paths and fail-closed construction |
| Trade Plan | Read-only V0.2 | Precomputed plan contract |
| Trade Lifecycle | Read-only V0.3 projection | Runtime read-only projection wired |
| External simulator/broker | NOT VERIFIED | No external account or broker connection |
| Cloud market data | NOT VERIFIED | TickFlow and OpenD cloud acceptance incomplete |
| Notifications | CONFIGURED/UNVERIFIED | Configuration is not phone-receipt evidence |
| Live trading | BLOCKED | `LIVE_TRADE=NO` |

## Promotion stages

### Stage 0 — Offline deterministic simulation

Required:

- factory-issued Paper capability only;
- explicit permission evidence;
- fresh reconciliation and market-data context;
- independent durable execution and Shadow stores;
- deterministic order identity and append-only journal;
- no network, provider, broker, scheduler, notification, or live-trade I/O;
- CI and Research Radar tests pass at the exact head.

Exit evidence:

- order lifecycle result is auditable;
- Shadow decision and execution result share the same intent/evidence lineage;
- restart/replay does not silently resubmit.

### Stage 1 — Cloud read-only observation

Required:

- cloud source identity and exact source revision;
- timestamp/currentness and closed-bar status;
- bounded latency samples with source-to-worker and worker-to-cache separated;
- disconnect, stale, duplicate, out-of-order, and recovery evidence;
- no order mutation and no admission promotion.

Exit evidence:

- TickFlow WebSocket continuity/recovery accepted for the intended A-share scope;
- OpenD capability/permission matrix accepted for the intended US scope;
- no unsupported “real-time” claim from cached or simulated data.

### Stage 2 — Shadow lifecycle

Required:

- Trade Plan V0.2 precomputed before trigger;
- fast trigger updates only price, volume, stop distance, position and freshness;
- explicit WAIT / NO_TRADE / ENTRY_BLOCKED reasons;
- position-management projection for 1R/2R, invalidation, timeout, disconnect and multi-timeframe conflict;
- notification delivery remains advisory and separately evidenced.

Exit evidence:

- repeated historical/replay scenarios produce stable decisions;
- all non-trades have a reason;
- no order adapter call occurs.

### Stage 3 — External Paper account

Required:

- user-authorized simulator account and exact account identity;
- read-only discovery/reconciliation first;
- order placement remains explicitly disabled until account, buying power, positions, open orders and fills are fresh;
- idempotency, restart, cancel/replace, partial fill and ambiguous submission tests;
- independent kill switch and rollback procedure.

Exit evidence:

- controlled test order only after a separate approval;
- broker acknowledgement and fill evidence are matched to local intent;
- no live account or live endpoint is reachable from the Paper path.

### Stage 4 — Automation consideration

Not enabled by this matrix. Requires a separate safety review covering:

- live-trade isolation;
- credential and endpoint isolation;
- maximum loss and exposure limits;
- human emergency stop;
- soak test and incident recovery;
- independent sign-off.

## Non-negotiable gates

```text
PAPER_AUTO_READY=NO
RADAR_ADMISSION=BLOCKED
SOURCE_ARBITER_ADMISSION=BLOCKED
LIVE_TRADE=NO
```

A passing offline simulation is evidence that the local Paper path works. It is not evidence of cloud data reliability, external simulator access, phone delivery, or live-trading readiness.

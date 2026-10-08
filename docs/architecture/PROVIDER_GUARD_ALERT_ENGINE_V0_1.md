# STOCK RAZOR Provider Guard Alert Engine V0.1

Status: STACKED IMPLEMENTATION / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Convert Provider Lifecycle / Cost Guard assessments into meaningful alert
transitions and route them through the repository's existing Notification
Gateway.

This slice does **not** create a new push stack. It reuses
`NotificationService.send_with_results(..., route_type="alert")`.

## State-transition rule

Provider Guard notifications are transition-driven:

- first active lifecycle problem -> `ACTIVE`;
- changed active problem/health/approval state -> `CHANGED`;
- identical state -> no notification;
- previously active problems disappear -> `CLEARED`.

A clear event means only that the previously observed negative conditions are
no longer present. It does **not** claim the provider is HEALTHY and does not
change Data, Radar, or Trading admission.

A provider effective health of WARNING / DEGRADED / RATE_LIMITED / FAILED /
EXHAUSTED / EXPIRED is itself alert-worthy even when the Guard assessment has
no explicit quota/credential/cost alert.

## Aggregation

One state transition produces one aggregated provider event containing:

- provider ID;
- effective health;
- highest severity;
- stable alert codes;
- human-readable internal Guard messages;
- observation timestamp;
- decision criticality;
- projected exhaustion time when known;
- whether user approval is required.

This avoids sending multiple push messages for one provider state change.

## Notification Gateway

The sink uses:

- `route_type="alert"`;
- severity from Guard state;
- stable state-scoped `dedup_key`;
- state-scoped `cooldown_key`;
- structured payload for downstream channels.

Existing notification routing/noise controls remain authoritative.

## Permission separation

Every event and structured payload is fail-closed:

- `auto_spend_permitted=false`;
- `radar_admission=UNCHANGED`;
- `trading_admission=UNCHANGED`;
- `live_trade=false`;
- `research_only=true`.

The notification layer cannot recharge, upgrade plans, authorize fallback,
change Radar admission, submit Paper orders, or enable live execution.

## Error hygiene

Notification dispatch failures store/log only the exception type in this bridge.
Raw provider failure text is not copied into Provider Guard alert state.

## Non-goals

V0.1 does not:

- schedule provider probes;
- decide Provider Health;
- decide Data Admission;
- qualify fallback;
- persist alert-transition state across process restarts;
- retry notification delivery independently of the existing Notification
  Gateway;
- authorize spend or execution.

Persistent transition state and delivery telemetry are later slices if needed.

## Stacked-development note

This implementation is developed above the provider runtime-ingest stack. It is
not eligible to merge until prerequisites are merged and the final diff is
rebuilt from canonical `main` with fresh exact-head CI and fresh Code Owner
approval.

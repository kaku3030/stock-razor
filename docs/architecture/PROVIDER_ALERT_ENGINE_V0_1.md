# STOCK RAZOR Provider Alert Engine V0.1

Status: STACKED IMPLEMENTATION / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Convert Provider Lifecycle snapshots and the existing `assess_provider()`
guard policy into deterministic alert state transitions.

The engine is intentionally separate from notification delivery.

It does not:

- poll providers;
- send messages;
- choose notification channels;
- change provider plans or billing;
- make Data Admission decisions;
- authorize Radar;
- place Paper or live orders.

## Transition model

Each provider alert is tracked by stable alert code.

Possible transition states:

- `OPEN` — alert code becomes active;
- `UPDATED` — the same alert code changes severity/message;
- `RESOLVED` — a previously active alert code is no longer desired.

Repeated identical active states emit no transition.

Older provider evidence is rejected fail-closed and cannot roll active alert
state backward. The same evidence timestamp may be re-evaluated later because
credential-expiry policy can legitimately cross time bands without new provider
evidence.

## Health-state policy

`UNKNOWN` and `HEALTHY` do not create generic runtime alerts.

| Runtime health | Generic severity |
| --- | --- |
| WARNING | WARNING |
| DEGRADED | WARNING |
| RATE_LIMITED | WARNING |
| FAILED | CRITICAL |
| EXHAUSTED | CRITICAL |
| EXPIRED | CRITICAL |

Specific existing guard alerts take precedence where they already explain the
same state. Examples:

- `BILLING_STATUS_EXHAUSTED` suppresses duplicate
  `RUNTIME_HEALTH_EXHAUSTED`;
- `CREDENTIAL_STATUS_FAILED` suppresses duplicate
  `RUNTIME_HEALTH_FAILED`;
- `CREDENTIAL_STATUS_EXPIRED` suppresses duplicate
  `RUNTIME_HEALTH_EXPIRED`.

Transport degradation and rate limiting remain explicit generic runtime alerts
because the current guard assessment has no more-specific code for them.

## Governance carried by every transition

Every transition is explicitly:

- `research_only=true`;
- `data_admission=NOT_EVALUATED`;
- `radar_admission=BLOCKED`;
- `live_trade=false`.

The engine reuses existing Provider Guard cost rules. Automatic spend remains
forbidden and `AUTO_RECHARGE_ENABLED` retains
`user_approval_required=true`.

## Notification boundary

V0.1 stops at typed transitions and stable `alert_key` values.

A later Notification Gateway slice may route these transitions through the
repository's existing `route_type="alert"` notification stack with
deduplication/cooldown. Notification failure must not mutate lifecycle state or
change Radar/trading permissions.

## Stacked-development note

This implementation is developed above the provider runtime-ingest stack.
It is not eligible to merge until prerequisites are merged and the final diff
is rebuilt from current canonical `main` with fresh exact-head CI and fresh
Code Owner approval.

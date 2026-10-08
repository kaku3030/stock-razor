# STOCK RAZOR Provider Notification Gateway V0.1

Status: STACKED IMPLEMENTATION / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Bridge typed Provider Alert Engine transitions into the repository's existing
notification stack.

V0.1 deliberately reuses `NotificationService.send_with_results()` with:

- `route_type="alert"`;
- existing configured channels;
- existing noise-control / dedup reservation;
- existing cooldown policy;
- existing per-channel diagnostics.

It does not introduce a new sender or a parallel push system.

## Input gate

Only `ProviderAlertTransition` is accepted.

Before any send, the gateway requires:

- `research_only=true`;
- `data_admission=NOT_EVALUATED`;
- `radar_admission=BLOCKED`;
- `live_trade=false`;
- timezone-aware evidence/evaluation timestamps;
- evaluation time not earlier than evidence;
- exact stable alert identity
  `provider_lifecycle:<provider_id>:<code>`;
- constrained provider/code identity tokens and enum-typed state/severity/health.

A policy violation raises before NotificationService is called.

## Routing and noise control

All sends use the existing alert route.

Dedup key contains:

- stable alert key;
- transition state;
- severity;
- a deterministic digest of the exact evidence timestamp;
- a deterministic digest of the internally generated alert message.

Cooldown is transition- and evidence-specific. A fresh `RESOLVED` transition
or a later re-open cannot be suppressed by an earlier incident's cooldown.

Resolved transitions preserve the originating alert severity so recovery from a
critical incident is not silently dropped by notification minimum-severity
policy.

## Safe diagnostics

The gateway returns a reduced dispatch result containing only:

- dispatched/attempted;
- success;
- status;
- channel;
- safe error code;
- retryable;
- non-negative latency.

Raw sender diagnostics and raw exception messages are not retained. On a
gateway exception, only the exception class name is returned. Sender
`dispatched`, `success`, and `retryable` fields are accepted only when
they are actual booleans; truthy strings or other malformed values fail closed.

## Failure separation

Notification failure is diagnostic-only.

It must not:

- mutate Provider Lifecycle evidence;
- reopen or resolve Alert Engine state;
- change Data Admission;
- change Radar Admission;
- enable fallback;
- authorize spend;
- authorize Paper or live execution.

The lifecycle/alert state is authoritative; notification is downstream delivery.

## Stacked-development note

This implementation is developed above Provider Alert Engine V0.1 and the
provider runtime-ingest stack. It is not eligible to merge until prerequisites
are merged and the final diff is rebuilt from canonical `main` with fresh
exact-head CI and fresh Code Owner approval.

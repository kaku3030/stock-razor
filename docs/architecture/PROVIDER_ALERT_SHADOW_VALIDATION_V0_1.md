# STOCK RAZOR Provider Alert Shadow Validation V0.1

Status: STACKED IMPLEMENTATION / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Run the Provider Alert Engine against real provider-runtime snapshots while
keeping notification delivery completely disabled.

This slice creates a deterministic shadow journal of **would-be** alert
transitions so the alert policy can accumulate runtime evidence before any
active notification rollout.

## Shadow behavior

For each accepted Provider Lifecycle snapshot:

1. the existing Provider Alert Engine performs all causal/staleness checks;
2. OPEN / UPDATED / RESOLVED transitions are converted into deterministic
   shadow events;
3. the validator records aggregate counts and provider/code coverage;
4. no Notification Gateway or sender is invoked.

Each shadow event explicitly carries:

- `shadow_only=true`;
- `delivery_attempted=false`;
- `research_only=true`;
- `data_admission=NOT_EVALUATED`;
- `radar_admission=BLOCKED`;
- `live_trade=false`.

## Deterministic journal

The shadow event ID is a SHA-256-derived identity over the typed transition
fields, including provider, code, state, severity, health, evidence timestamp,
evaluation timestamp, and alert key.

The journal is append-only from the validator's public surface and returns
immutable tuple snapshots.

Repeated identical runtime states do not create duplicate events because the
Alert Engine is stateful. An additional event-ID guard keeps the journal
idempotent under identical transition replay.

## Summary

V0.1 reports:

- snapshots observed;
- total transitions;
- OPEN / UPDATED / RESOLVED counts;
- completed alert cycles;
- currently active alert count;
- provider coverage;
- alert-code coverage;
- `COLLECTING` or `EVIDENCE_AVAILABLE` shadow status.

A RESOLVED transition counts as one completed alert cycle because the Alert
Engine can emit RESOLVED only for a previously active alert.

## No automatic promotion

The shadow summary always sets:

`notification_activation_permitted=false`

regardless of sample count, apparent quality, or completed cycles.

V0.1 deliberately has **no threshold that can enable active notifications**.
Any future rollout/admission decision must be a separate explicit policy slice
with its own evidence and approval gate.

## Failure semantics

Older provider evidence and causal time reversal are rejected by the Alert
Engine before shadow counters or journal state are mutated.

Shadow validation cannot change:

- Provider Lifecycle health;
- Data Admission;
- Radar Admission;
- provider fallback;
- billing;
- Notification Gateway state;
- Paper or live execution.

## Relationship to execution shadow

This is **not** the existing execution `live_shadow.py` capability.

Execution shadow previews broker/order risk and execution eligibility. Provider
alert shadow validates operational alert behavior only. The two journals must
remain separate.

## Stacked-development note

This implementation is developed above Provider Notification Gateway V0.1. It
is not eligible to merge until prerequisites are merged and the final diff is
rebuilt from current canonical `main` with fresh exact-head CI and fresh Code
Owner approval.

# STOCK RAZOR Provider Shadow Runtime Pipeline V0.1

Status: STACKED IMPLEMENTATION / SHADOW-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Connect governed provider runtime evidence to the zero-delivery Provider Shadow
Alert Validation harness without adding file, network, scheduler, notification,
Paper, or live-trading side effects.

One pipeline instance owns:

- one `ProviderRuntimeObserver`;
- one `ProviderShadowAlertValidator`.

This preserves field-level evidence ordering and stateful alert transitions
across runtime cycles.

## Supported V0.1 inputs

The pipeline reuses the existing runtime-evidence builders for:

- moomoo OpenD live-feed heartbeat;
- CN Eastmoney-primary / Tencent-fallback cloud observation;
- Alpaca adapter runtime events;
- sanitized negative provider probes.

It does not implement a second parser for any provider.

## Preflight before observer mutation

The pipeline builds and validates all observations first.

Before writing evidence into the shared observer it requires:

- timezone-aware `now`;
- `now >= incoming evidence observed_at`;
- `now >= existing provider snapshot observed_at` when a provider already
  has runtime evidence.

This prevents a time-reversal call from mutating observer state before the
shadow layer rejects it.

The underlying Observer still provides field-level monotonicity, so older
runtime evidence cannot roll a provider backward or synthesize a false
recovery.

## Output

Each `ProviderShadowRuntimeCycle` exposes:

- source;
- provider snapshots;
- shadow alert results;
- provider IDs;
- transition count;
- planned notification count;
- actual notification count.

`actual_notification_count` is always zero.

The cycle uses `validation_status=VALIDATED`; this describes only the
shadow-pipeline contract. It is not Provider Health PASS, Data Admission PASS,
Radar Admission, Paper Trading admission, or execution authorization.

## Non-goals

V0.1 does not:

- read runtime files;
- poll APIs;
- start threads or schedulers;
- send notifications;
- persist alert-center rows;
- change fallback;
- change billing;
- submit Paper orders;
- submit live orders.

A later runtime-wiring slice may read already-governed runtime outputs and feed
this pipeline. That wiring must preserve all existing data/admission/execution
gates.

## Stacked-development note

This implementation is developed above Provider Shadow Alert Validation V0.1.
It is not eligible to merge until prerequisites are merged and the final diff
is rebuilt from canonical `main` with fresh exact-head CI and fresh Code
Owner approval.

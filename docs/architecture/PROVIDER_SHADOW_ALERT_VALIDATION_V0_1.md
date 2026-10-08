# STOCK RAZOR Provider Shadow Alert Validation V0.1

Status: STACKED IMPLEMENTATION / SHADOW-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Validate the real Provider Alert Engine and Provider Notification Gateway
together without sending any external notification.

The harness intentionally uses:

- the real stateful `ProviderAlertEngine`;
- the real `ProviderNotificationGateway`;
- an injected in-memory NotificationService-compatible sink.

No alternate alert logic or notification-key logic is implemented for shadow
mode.

## What shadow validates

For each `RuntimeProviderSnapshot`, the harness can verify:

- OPEN / UPDATED / RESOLVED transition generation;
- specific-vs-generic alert de-duplication;
- rendered notification content;
- alert route;
- severity;
- evidence-specific dedup key;
- evidence/state-specific cooldown key;
- structured governance payload.

Repeated alert state is evaluated by the same stateful Alert Engine, so a
second identical state produces no new notification plan.

## Zero-delivery guarantee

The shadow sink returns:

- `dispatched=false`;
- `success=false`;
- `status=shadow_only`;
- no channel results.

The validator rejects any shadow dispatch that reports an attempted or
successful external notification.

`actual_notification_count` is therefore always zero in V0.1.

## Governance

Every shadow result remains:

- research-only;
- Data Admission `NOT_EVALUATED`;
- Radar Admission `BLOCKED`;
- live trade disabled.

Shadow validation is not Provider Health PASS, Data Admission PASS, Radar
admission, Paper Trading admission, or execution authorization.

## Failure separation

The harness does not:

- start a background polling worker;
- persist alert state to the alert-center database;
- call configured notification channels;
- change provider fallback;
- change billing;
- submit Paper orders;
- submit live orders.

Stale provider evidence is rejected by the real Alert Engine exactly as in the
non-shadow path.

## Next slice

After the runtime-ingest, alert-engine, notification-gateway, and shadow
contracts are formally merged and validated, a later scheduler/runtime wiring
slice may feed real provider snapshots into this harness. Only after stable
shadow evidence should Paper Trading integration be considered.

## Stacked-development note

This implementation is developed above Provider Notification Gateway V0.1.
It is not eligible to merge until prerequisites are merged and the final diff
is rebuilt from canonical `main` with fresh exact-head CI and fresh Code
Owner approval.

# Active notification E2E acceptance V0.1 (not enabled)

> Design and acceptance contract only. **No outbound notification, AWS dispatch,
> provider query, broker call, scheduler, or automatic Paper/Live order is
> authorized by this document.**

## Baseline and ownership

- AI Monitor owns the single notification runtime and its delivery receipts.
  Do not introduce a second scheduler, sender or route owner.
- Existing Operations `/status` separates configured channels/routes from
  `notification_delivery_evidence=NOT_VERIFIED`; keep that distinction.
- Existing alert rule `/rules/{rule_id}/test` is an evaluation dry-run, **not
  guaranteed network-free**: rule evaluation may fetch market data. Do not use
  this endpoint as proof of a no-provider-I/O notification probe.
- PR #540 acceptance stages remain controlling. #539 offline Paper success
  proves no cloud notification or mobile receipt.

## Evidence state machine

| State | Minimum independent proof | May claim |
| --- | --- | --- |
| NOT_CONFIGURED | No complete route secrets/targets | Not ready |
| ROUTE_CONFIGURED | Valid non-secret channel/route projection | Only configuration |
| SEND_ATTEMPTED | Explicitly approved bounded test, timestamp and sanitized route ID | Attempt only |
| PROVIDER_ACKED | Provider-specific acceptance response and attempt correlation | Provider accepted, **not phone received** |
| PHONE_RECEIVED_VERIFIED | Human/device receipt evidence correlated to exact attempt ID and delivery time | Delivery reached the device |
| ERROR_OR_UNKNOWN | Timeout, 401/403, 429, exhausted credits, network loss, missing logs, identity mismatch | Fail closed |

Only the last state passes the *phone delivery* gate. Provider HTTP 200 does
not substitute for a device receipt. Never store token, webhook URL, chat ID
or user-private message content in a public issue, test fixture or report.

## Alert-candidate contract (dry-run stage)

Every projected candidate needs:

- `event_kind`, `source_family`, `source_revision`,
  `runtime_generation`, `evidence_as_of_utc`, and an incident reason;
- independent source/currentness/closed-bar qualifications, preserving UNKNOWN;
- `session_state` from the authoritative market calendar/runtime;
- stable idempotency key for *same episode*, with transition/recovery identity;
- explicit `advisory_only=true`, `send_authorized=false`,
  `order_mutation_allowed=false` during Shadow validation.

An incident reported only because a Friday bar is the latest bar on Sunday
must NOT page as a real-time market outage. In an unknown session, classify
UNKNOWN and defer market-price alerts. A stale **heartbeat** can still be a
system-health candidate when there is independent evidence the worker is
supposed to run, but it is not a trade signal.

## Adversarial acceptance matrix

| Case | Expected outcome |
| --- | --- |
| One probe success or cached quote | Observational only; no continuous-feed or delivery PASS |
| Provider disconnect and stale observation in open session | Candidate with source identity and reason; **no send** in dry-run |
| Duplicate event / restart / replay | One idempotency key, no duplicate send |
| Older sequence or future timestamp | Reject or mark UNKNOWN; cannot synthesize recovery |
| Session closed or session unknown | No false market-staleness paging |
| Channel configured without consent/phone receipt | `ROUTE_CONFIGURED` only |
| Provider 200 / accepted | `PROVIDER_ACKED`, **not** `PHONE_RECEIVED_VERIFIED` |
| 401/403, quota exhaustion, 429, timeout | `ERROR_OR_UNKNOWN`, bounded backoff, no silent retry storm |
| No route or route filtered out | Reasoned BLOCKED, never success |
| Emergency stop, source gate blocked | Notification may describe the fault, cannot enable any trading gate |
| Upstream record contains a secret or raw provider payload | Output must be sanitized before log, UI or message |

## Controlled rollout sequence

1. Unit tests: pure candidate projection, negative cases and dry-run outbox
   with `actual_notification_count=0`.
2. Isolated local evidence: route resolution without network and without
   calling market-data providers; no synthetic 'phone receipt' claims.
3. **Separate user approval** for one bounded real test to a designated
   channel. Record test identity, start/end, provider ACK, and mobile receipt
   independently, with no secret values.
4. Only after CI, source/SHA identity, runtime trace and operator approval,
   deploy a notification-only Cloud Shadow; measure queue age, delivery time,
   duplicates and outage recovery. Report percentiles only from real samples.
5. Later enable guarded advisory alerts via the canonical AI Monitor owner.
   Trading remains out of scope.

## Immutable safety policy

```text
PAPER_AUTO_READY=NO
RADAR_ADMISSION=BLOCKED
SOURCE_ARBITER_ADMISSION=BLOCKED
LIVE_TRADE=NO
```

No route can authorize an order. No notification delivery claim can promote
source, Radar, Paper or Live admission. Any drift is a review blocker.

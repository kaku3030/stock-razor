# Paper Auto Acceptance Matrix V0.1

Status: acceptance plan only. This document does not authorize Paper Auto,
production promotion, broker access, or live trading.

## Purpose

Separate three claims that must not be conflated:

1. the offline Paper engine is implemented;
2. the Paper runtime is safe under restart, rejection, and fault conditions;
3. qualified market data can safely drive a cloud Paper session.

Only the first claim is currently supported by implementation evidence. The
third remains blocked until TickFlow/OpenD data qualification and an explicit
end-to-end evidence binding are complete.

## Gates

| Gate | Required evidence | Expected result | Current state |
| --- | --- | --- | --- |
| P0 static contract | `ExecutionEngine`, Paper admission, and runtime tests | Deterministic intent, risk and lifecycle contracts pass | PASS in CI |
| P1 startup barrier | Runtime starts only after reconciliation | `NEW -> READY` only after account reconciliation | PASS in CI |
| P2 restart recovery | Persisted journal reopened with a new Paper adapter | Existing orders replay; duplicate retry does not place again | PASS in CI |
| P3 negative/fault matrix | Unknown permission, stale data, thread mismatch, reconcile failure, ambiguous submission | No adapter mutation; expected failures remain fail-closed | PASS in CI; expand soak evidence |
| P4 multi-session soak | Repeated start/refresh/process/stop across isolated sessions | No duplicate intent, fill, broker identity, or journal corruption | NOT_RUN as a bounded soak |
| P5 qualified data binding | Timestamped qualified snapshot/currentness and account generation bound to permission | Data evidence is fresh, complete, and causally before execution | BLOCKED: TickFlow/OpenD qualification pending |
| P6 cloud Paper E2E | Cloud runtime, notification trace, restart and reconciliation evidence | Realistic cloud Paper loop with no live side effect | BLOCKED: no AWS deployment authorized |

## Promotion rule

`PAPER_AUTO_READY` must remain `NO` unless P0–P6 are independently evidenced.
Passing P0–P3 proves only offline safety behavior; it cannot promote a live
data source or authorize an automatic Paper session.

The following are never sufficient on their own:

- a configured webhook;
- a green unit test using synthetic market data;
- a local OpenD session;
- a stale or cache-only snapshot;
- a successful process start without restart and reconciliation evidence.

## Evidence record

Each executed gate should record:

- exact main/PR commit;
- test or run identifier;
- start/end UTC timestamps;
- source and snapshot identity;
- runtime and account generation;
- adapter mutation count and journal event count;
- PASS/FAIL/UNKNOWN with a bounded reason;
- whether any external request, cost, notification, or broker side effect occurred.

Unknown evidence is not converted to PASS. A failed or incomplete gate keeps
the corresponding admission blocked.

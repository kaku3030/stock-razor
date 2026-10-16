# OpenD dynamic subscription: closed-session acceptance matrix

**Scope:** US 1-minute K-line subscription control plane, proposed in PR #812.
The market being closed is **not itself a reason to deny** a subscription
request. Provider connectivity, a current entitled account, the OpenD SDK,
instance quota, rate limits and the selected quote session are independent
preconditions. This document does **not** authorize AWS runtime mutations.

Futu's provider API has distinct `subscribe(...)`,
`query_subscription(...)` and `unsubscribe(...)` operations. The documented
US K-line options include `extended_time` and `session=Session.ALL`;
`Session.OVERNIGHT` by itself is not allowed for US quotes. The provider
documentation cautions to wait at least one minute before unsubscribing.
`is_first_push=True` can replay cached data, including after reconnect.
In this unmerged PR, the Python Futu K_1M adapter now explicitly passes
`session=Session.ALL` for `session_mode="ALL"`, and preserves that exact
semantic stream key for subsequent callbacks. It rejects missing SDK
`Session.ALL` support and unsupported `OVERNIGHT`-only requests. The
manager groups regular and ALL candidates into separate provider batches;
a direct adapter call with mixed scopes fails closed. **These are offline
behavioral contracts, not provider-side ACK or live cloud evidence.**

References (official provider docs):
https://openapi.futunn.com/futu-api-doc/en/quote/sub.html
https://openapi.futunn.com/futu-api-doc/en/quote/query-subscription.html

## Two separately required qualifications

| Evidence | During closed session | Must wait for active matching market session? |
| --- | --- | --- |
| Live OpenD process and QOT_RIGHT/entitlement readback | Yes, if connected | No |
| Query subscription use/remaining allowance | Yes, if connected | No |
| Dry-run candidate plan and quota/ownership/rate safety | Yes | No |
| Bounded `Qot_Sub` result and `query_subscription` read-after-write | Technically possible; needs current SDK/provider entitlement and authorized control-plane window | No |
| Safe `Qot_UnSub`, respecting provider minimum interval | Possible with limits | No |
| First cached K-line or historical readback | Possible with subscribed access | No; research-only |
| **New** 1m bar, source time advance, 5m/15m/D1 coherence | Cannot be inferred from ACK or cached push | Yes, only when bars are due |
| Publisher callback closure, exchange finality, extended/overnight rights | Cannot be inferred from closed-session ACK | Yes, in each session with actual data |
| Radar/source arbiter admission or trading | **BLOCKED** | Requires separate complete trading-grade gates |

## Fail-closed ECT off-session procedure

1. **Read-only first**: record exact repo SHA and runtime instance ID,
   session phase, clock, adapter + SDK version, and current
   `query_subscription` quota/right evidence. Require valid age and
   sufficiently free quota (including per-type accounting), not a remembered
   quota from the prior session.
2. **Preview first**: simulate additions/removals, confirm no real requests,
   list requested `session_mode` and underlying SDK mapping to `Session.ALL`
   or appropriate extended-hours setting; reject ambiguous mode.
3. **Only after separately approved runtime control-plane authorization**:
   subscribe one non-baseline pilot, read OpenD provider ACK,
   `query_subscription` exact per-stream visibility and connection owner.
   Never execute `unsubscribe_all`. Observe the documented 60-second
   minimum retention before a targeted unsubscribe.
4. If a batch raises or transport disconnects, mark `UNKNOWN`; do not infer
   the provider rolled back. Reconcile against a fresh quota/list and only a
   newly proven runtime incarnation may recover.
5. Repeat readback across the transition into a trading session and into
   another closed session; distinguish `is_first_push` replay from genuine
   provider-timestamp advance.
6. Until source age, multi-timeframe continuity, provider rights, bar
   closure and post-close finality are independently proven:
   `RADAR_ADMISSION=BLOCKED`,
   `SOURCE_ARBITER_ADMISSION=BLOCKED`,
   `PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO` and
   `TRADE_EXECUTION=NO`.

## What PR #812 tests today

Offline fake adapter tests verify that the manager does not unnecessarily
gate the control plane on wall-clock session phase, *while still requiring*
fresh verified quota. No test here contacts OpenD, verifies `Qot_Sub` ACK,
rights, provider session flags or actual after-hours/overnight K-lines.
The updated adapter and manager are covered by fake OpenD SDK/context
tests for `Session.ALL` argument propagation, callback semantic identity,
unsupported SDK session support, mixed batch grouping and runtime bridge
ownership. Genuine `Qot_Sub` provider ACK followed by
`query_subscription` reconciliation is **not implemented or verified**
by this PR; rights and fresh 1m K-lines remain independent gates.

The existing cloud runtime is a different SHA from PR #812, which is open
and not deployed. A green CI cannot qualify cloud operations.

Off-session **preparation** is useful and should happen before the market
opens. Real closed-bar and first live K-line acceptance remains a separate
market-time requirement.

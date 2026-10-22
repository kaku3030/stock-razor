# Paper Trading Acceptance Matrix V0.2

> Scope: controlled Paper progression only. This document does not authorize AWS deployment, paid market-data calls, external broker calls, notification sends, or live trading.

## Current baseline

| Layer | Current state | Evidence |
|---|---|---|
| Offline Paper runner | READY (OFFLINE ONLY) | PR #539 canonical reconcile → Shadow → Paper Engine; PR #627 same-store eight-restart deterministic soak exact-head CI PASS |
| Durable execution/shadow stores | IMPLEMENTED | Separate SQLite paths and fail-closed construction |
| Trade Plan | Read-only V0.2 | Precomputed plan contract |
| Trade Lifecycle | Read-only V0.3 projection | Runtime read-only projection wired |
| External simulator/broker | LOCAL + AWS SIM READ-ONLY PASS / PAPER BLOCKED | Last read-only cloud run #38201521471 (2026-10-12): one active US SIM account, four scoped readbacks PASS; old positions require review, native SIM deal APIs unsupported, exact account identity unproven |
| Cloud market data | PARTIAL / ADMISSION BLOCKED | AWS US controller healthy but canonical snapshot stale (weekend), US bar closure unproven; A-share cloud historical fallback PASS, currentness unproven; TickFlow cloud premium acceptance incomplete |
| Notifications | CONFIGURED/UNVERIFIED | Configuration is not phone-receipt evidence |
| Live trading | BLOCKED | `LIVE_TRADE=NO` |

The Operations page reads `GET /v1/operations/paper-controls` and
shows the Paper UI's read-only/mutation, broker-I/O, provider-I/O,
external-account-evidence and phone-receipt states. It also lists available
and blocked operator actions with their reasons. This is status display only:
it does not initiate offline runs, discover broker accounts, submit/cancel
orders, or send notifications. A control-read failure is shown separately and
does not suppress the main operations status.

## A-share cloud read-only observation (2026-10-11 audit)

An actual AWS-backed read-only MCP query for ETF `159363` returned
`status=PASS`, `research_only=true`, a **Tencent fallback**
(`fallback_from=eastmoney`, `fallback_reason=CloudObservationError`),
and bounded historical daily/15m rows ending **2026-10-09**. The
Tencent intraday timestamp grid/semantics were `PASS/BAR_END`, while
`intraday_currentness_proven=false` and `can_confirm_signal=false`.
This is **genuine cloud offline/historical data availability**, not a
current/streaming TickFlow feed and not a live Entry Gate. On Sunday a
Friday end-of-session bar must not trigger a false live-data outage or
signal.

The CN observer installer now has **code prepared** for a slower
weekend provider-request cadence (default 900 seconds versus the
existing 60-second weekday cadence); it preserves normal weekday polling
and records the next interval in each actual provider observation.
It does **not** fabricate a refreshed quote on sleep. The manual
CN deployment workflow also withholds raw SSM stdout/stderr from the
PUBLIC Actions log and tests the Eastmoney UNKNOWN versus Tencent
BAR_END timestamp semantics without upgrading them to currentness.
These changes are only deployed after independently approved actual AWS
deployment. CI proof is not proof that the running worker is updated.

## AWS OpenD SIM-only readback readiness (2026-10-11)

Windows local evidence: a single ACTIVE US `SIMULATE / STOCK_AND_OPTION`
account was selected with `TrdMarket.US`. Queries using an explicit
in-memory simulator account ID returned **one balance row**, **four existing
position rows**, **zero current orders** and **zero historical orders** in
the reviewed ~90-day period. This is genuine LOCAL read-only broker I/O,
not cloud authorization, not a simulated fill receipt, and not an
unblocked Paper runtime. Real-account rows were never used for account
financial queries; no private account/position amounts are in GitHub.

The preexisting, explicitly manual
`.github/workflows/aws-ssm-sim-account-discovery.yml` now provides an
AWS **read-only** continuation when separately dispatched and approved.
The fixed SSM target queries at most one uniquely identified ACTIVE US SIM
account with four non-mutating RPCs: `accinfo_query`,
`position_list_query`, `order_list_query`, and
`history_order_list_query`. It returns **only finite status labels and
review-required booleans**, never account identifiers, position symbols,
quantities, cash/asset amounts, or raw provider errors. Query source
identity and the exact AWS runtime version must still be checked
independently; the GitHub `source_revision` is the workflow commit, **not**
proof of the OpenD worker version. A code merge does not execute this
manual workflow or demonstrate that cloud OpenD authentication succeeds.

**Executed evidence** (2026-10-11 11:29 UTC): the first authorized
manual `AWS SSM SIM Account Discovery` run
[38135716291](https://github.com/kaku3030/stock-razor/actions/runs/38135716291)
completed `SUCCESS` at workflow source SHA
`7df56f2ce8ea562f5e7906ccc8b339fad9590b25`. Its public-safe summary
reported `opend_reachable=true`, `query_status=PASS`,
`simulated_us_account_count=1`, and all of
`balance_readback`, `positions_readback`, `orders_readback`,
`history_readback` equal `PASS`. `position_review=REQUIRED`,
`order_review=NOT_REQUIRED`, `sim_native_fills=UNSUPPORTED_BY_OPEND`,
`paper_preflight=BLOCKED`, and `live_trade=false`. This proves the
**AWS-hosted OpenD accepts four SIM-only read-only RPCs** at that time,
without using the user's Windows machine as a source. It does *not*
independently attest that AWS and Windows refer to the exact same
simulated account ID, prove any SIM fills, change the persistent cloud
US market-data worker's older SHA, or authorize broker mutation.

The next workflow revision also gates GitHub job `SUCCESS` on **all four**
SIM readbacks and a single uniquely identified US SIM account. Without
that guard a shell-only SSM `Success` could conceal a provider-level
`ERROR`, `NOT_RUN`, multiple candidates, or missing funds/positions.
Position review can remain `REQUIRED` while read-only connectivity
passes; Paper admission continues `BLOCKED`.

The official OpenD `deal_list_query` SIM path is unsupported.
Order-history `dealt_qty/dealt_avg_price` plus cash/position changes
can provide **corroboration**, not a replacement for independent native
broker fill acknowledgements. Pending a specifically reviewed alternative
receipt source, the external SIM fill/readiness gate stays `BLOCKED`.
Existing nonzero positions always demand operator review. No automatic
or manual SIM order is authorized by the AWS readback workflow.

## Position baseline and realized-fill evidence policy

The external SIM path now treats a position baseline as a separately bound
read-only evidence object. It must carry the exact account identity, account
generation, UTC observation timestamp, source, and read-only evidence ID.
Missing or stale provenance is `UNKNOWN`; an account, generation, source, or
evidence mismatch is `BLOCKED`.

`PaperFillReconciliation` remains a numeric corroboration for supervised
review. It is not a realized fill. A realized fill requires two distinct
before/after position baselines and a separate read-only provider evidence
record with filled quantity, average price, position delta, and exact
fee-aware cash movement. Intent, broker ACK, dispatch success, fixtures, or a
single readback cannot establish that fact. Until an independently authorized
native receipt source exists, the external Paper admission remains
`UNKNOWN`/`BLOCKED` and `PAPER_AUTO_READY=NO`. The pure
`assess_external_paper_admission` result `READY_FOR_SUPERVISED_REVIEW` is an
evidence disposition only; it never authorizes an order call.

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
- read-only fill evidence includes filled quantity and average price, and is
  cross-checked against the same-session position quantity delta and account
  cash movement **with independently evidenced total fees/taxes in the cash
  currency**: BUY outflow must equal notional + fees; SELL inflow must equal
  notional - fees. Missing fee evidence, out-of-scope FX/conversion,
  unrelated deposits/withdrawals, and unexplained cash deltas remain
  `BLOCKED` (not tolerated or inferred);
- missing or unsupported fill queries, including moomoo SIM
  `deal_list_query=-1`, remain `BLOCKED` regardless of a plausible
  order-history/position/cash correlation. That correlation is research
  evidence and must not impersonate broker-native execution receipts;
- any pre-existing non-zero position remains a manual-review condition even
  when the quantity/price/cash cross-check is internally consistent;
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

## Current 2026-10-12 status: Paper is not yet an autonomous cloud simulator

The AWS read-only [SIM Account Discovery #38201521471](https://github.com/kaku3030/stock-razor/actions/runs/38201521471)
was completed at 03:53 UTC. Its **sanitized** workflow evidence is
`opend_reachable=true`, `query_status=PASS`,
`simulated_us_account_count=1` and `balance_readback`,
`positions_readback`, `orders_readback`,
`history_readback=PASS`. Previously held SIM positions remain
`position_review=REQUIRED`; no current order review is required.
`account_evidence=OBSERVED_NOT_VERIFIED`,
`sim_native_fills=UNSUPPORTED_BY_OPEND`,
`paper_preflight=BLOCKED`, `paper_auto_ready=false`.
Source workflow revision is not an attested OpenD deployment revision.

This is *real non-mutating cloud OpenD/SIM API access*, **not** a placed
SIM order, automatic strategy fill, proof that the account equals the
local simulator account, or evidence of an approved cloud Paper runtime.
Futu's current `deal_list_query` and `history_deal_list_query`
do not support `TrdEnv.SIMULATE`:
[official docs](https://openapi.futunn.com/futu-api-doc/en/trade/get-order-fill-list.html).
No fake broker receipt should be manufactured by trusting an ACK or a
simulator fill fixture.

Offline Paper restart evidence improved independently via
[PR #627](https://github.com/kaku3030/stock-razor/pull/627):
eight restarts using the same durable execution journal and Shadow
store, followed by a ninth recovery, rejected duplicate intents,
verified unique monotonically restored simulated broker order IDs and
no duplicate adapter placements. Exact-head
[CI #38236252954](https://github.com/kaku3030/stock-razor/actions/runs/38236252954)
and [Radar #38236253028](https://github.com/kaku3030/stock-razor/actions/runs/38236253028)
PASS. That is **offline P4 partial evidence**; external SIM orders,
cloud soak, market source qualification and phone alert delivery are
still not proven. No Paper or live order is permitted by this note.

**Promotion disposition**:
`OFFLINE_PAPER=IMPLEMENTED` · `AWS_SIM_READBACK=PASS` ·
`EXISTING_POSITION_BASELINE=REVIEW_REQUIRED` ·
`SIM_FILL_RECEIPT=UNSUPPORTED_UNRESOLVED` ·
`PAPER_AUTO_READY=NO` · `RADAR_ADMISSION=BLOCKED` · `LIVE_TRADE=NO`.

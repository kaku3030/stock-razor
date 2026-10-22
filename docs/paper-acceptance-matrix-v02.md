# Paper Trading Acceptance Matrix V0.2

> Scope: controlled Paper progression only. This document does not authorize AWS deployment, paid market-data calls, external broker calls, notification sends, or live trading.

## Current baseline

| Layer | Current state | Evidence |
|---|---|---|
| Offline Paper runner | READY (OFFLINE ONLY) | PR #539 canonical reconcile â†’ Shadow â†’ Paper Engine; PR #627 same-store eight-restart deterministic soak exact-head CI PASS |
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
and blocked operator actions with their reasons. The permissions card is status display only. A separate manual offline scenario form now runs one user-entered synthetic BUY scenario through an isolated Paper engine and temporary stores. It never reads market data or strategy evidence, never discovers broker accounts, and has no broker/provider/notification/live-trading path. Temporary journals are discarded after the response. A scenario fixture may optionally display a synthetic fill; that is not a broker receipt or persistent Paper ledger. Sell scenarios remain disabled until a virtual position baseline is implemented.

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

### Stage 0 â€” Offline deterministic simulation

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

### Stage 1 â€” Cloud read-only observation

Required:

- cloud source identity and exact source revision;
- timestamp/currentness and close}Û-¢G§²ÚîÆ­yÙĞè=É‘•É%¹Ñ•¹Ğ°½¹Ñ•áĞèI¥Í­½¹Ñ•áĞ¤€´ø9½¹”è4(€€€€€€€¥˜Í•±˜¹É•½¹¥±¥…Ñ¥½¸¥Ì9½¹”èÉ…¥Í”á•ÕÑ¥½¹	±½­• ‰É•½¹¥±¥…Ñ¥½¸¥ÌÉ•ÅÕ¥É•ˆ¤4(€€€€€€€Í•±˜¹É¥Í­}Õ…É¹¡•¬¡¥¹Ñ•¹Ğ±Í•±˜¹É•½¹¥±¥…Ñ¥½¸±½¹Ñ•áĞ¤4(€€€€€€€¥˜Í•±˜¹ÍÑ½É”¹¡…Í}…µ‰¥Õ½ÕÍ}ÍÕ‰µ¥ÍÍ¥½¸ ¤èÉ…¥Í”á•ÕÑ¥½¹	±½­• ‰Á•¹‘¥¹œµÕÑ…Ñ¥½¸É•ÅÕ¥É•ÌÉ•Íå¹Œˆ¤4(€€€‘•˜É•½¹¥±”¡Í•±˜¤€´øI•½¹¥±¥…Ñ¥½¹M¹…ÁÍ¡½Ğè4(€€€€€€€‰…±…¹”€ôÍ•±˜¹±•‘•È¹‰…±…¹” ¤4(€€€€€€€¥˜‰…±…¹”¹ÍÑ…ÑÕÌ€ôô€‰-9=]8ˆè4(€€€€€€€€€€€Á½Í¥Ñ¥½¹Ì€ôÑÕÁ±”¡A½Í¥Ñ¥½¹M¹…ÁÍ¡½Ğ¡À¹Íåµ‰½°°À¹ÅÑä°À¹µ…É­•Ñ}Ù…±Õ”¤™½ÈÀ¥¸Í•±˜¹±•‘•È¹Á½Í¥Ñ¥½¹Ì ¤¤4(€€€€€€€€€€€¹½Ü€ô‰…±…¹”¹…Í}½˜4(€€€€€€€€€€€…½Õ¹Ğ€ô½Õ¹ÑM¹…ÁÍ¡½Ğ ‰Á…Á•Èˆ°‰…±…¹”¹‰Õå¥¹}Á½İ•È°‰…±…¹”¹•ÅÕ¥Ñä°¹½Ü°€‰Á…Á•Èˆ¤4(€€€€€€€€€€€Í¹…ÁÍ¡½Ğ€ôI•½¹¥±¥…Ñ¥½¹M¹…ÁÍ¡½Ğ¡…½Õ¹Ğ°Á½Í¥Ñ¥½¹Ì°…Í}½˜õ¹½Ü¤4(€€€€€€€•±Í”è4(€€€€€€€€€€€Í¹…ÁÍ¡½ĞõÍ•±˜¹…‘…ÁÑ•È¹É•½¹¥±” ¤4(€€€€€€€Í•±˜¹É•½¹¥±¥…Ñ¥½¸õÍ¹…ÁÍ¡½Ğ4(€€€€€€€¥˜Í¹…ÁÍ¡½Ğ¹…Í}½˜¥Ì9½¹”½È¹½ĞÍ¹…ÁÍ¡½Ğ¹½µÁ±•Ñ”½È…¹ä¡È¹¥‘•¹Ñ¥Ñä€„ôÍ¹…ÁÍ¡½Ğ¹…½Õ¹Ğ¹…½Õ¹Ñ}¥½ÈÈ¹Í½ÕÉ”€„ôÍ¹…ÁÍ¡½Ğ¹…½Õ¹Ğ¹Í½ÕÉ”½È¹½ĞÈ¹½µÁ±•Ñ”½È¹½ĞÈ¹™É•Í ™½ÈÈ¥¸Í¹…ÁÍ¡½Ğ¹É•Í½ÕÉ•Ì ¤¤èÉ…¥Í”á•ÕÑ¥½¹	±½­• ‰É•½¹¥±¥…Ñ¥½¸¥Ì¥¹½µÁ±•Ñ”½ÈÍÑ…±”ˆ¤4(€€€€€€€É•ÑÕÉ¸Í¹…ÁÍ¡½Ğ4(€€€‘•˜ÍÕ‰µ¥Ğ¡Í•±˜°¥¹Ñ•¹Ğè=É‘•É%¹Ñ•¹Ğ°½¹Ñ•áĞèI¥Í­½¹Ñ•áĞ¤€´ø=É‘•ÉI•½Éè4(€€€€€€€¥˜¥¹Ñ•¹Ğ¹¥¹Ñ•¹Ñ}¥¥¸Í•±˜¹É•½É‘Ì½È…¹ä¡”¹¥¹Ñ•¹Ñ}¥ôõ¥¹Ñ•¹Ğ¹¥¹Ñ•¹Ñ}¥™½È”¥¸Í•±˜¹©½ÕÉ¹…°¤èÉ…¥Í”á•ÕÑ¥½¹	±½­• ‰‘ÕÁ±¥…Ñ”¥¹Ñ•¹Ñ}¥ˆ¤4(€€€€€€€¥˜Í•±˜¹É•½¹¥±¥…Ñ¥½¸¥Ì9½¹”èÉ…¥Í”á•ÕÑ¥½¹	±½­• ‰ÍÑ…ÉÑÕÀÉ•½¹¥±¥…Ñ¥½¸¥ÌÉ•ÅÕ¥É•ˆ¤4(€€€€€€€Í•±˜¹É¥Í­}Õ…É¹¡•¬¡¥¹Ñ•¹Ğ±Í•±˜¹É•½¹¥±¥…Ñ¥½¸±½¹Ñ•áĞ¤4(€€€€€€€±•‘•É}­¹½İ¸€ôÍ•±˜¹±•‘•È¹‰…±…¹” ¤¹ÍÑ…ÑÕÌ€ôô€‰-9=]8ˆ4(€€€€€€€…Í¡}É•Í•ÉÙ•€ô±•‘•É}­¹½İ¸…¹¥¹Ñ•¹Ğ¹Í¥‘”¥ÌM¥‘”¹	Ud4(€€€€€€€€Œ¡•¬…¹‘ÕÉ…‰±äÉ•Í•ÉÙ”€©‰•™½É”¨İÉ¥Ñ¥¹œMU	5%QQ%9½È½¹Ñ…Ñ¥¹œ4(€€€€€€€€Œ…¹ä…‘…ÁÑ•È¸=Ñ¡•Éİ¥Í”„¡…Éµ±•ÍÌ¥¹ÍÕ™™¥¥•¹Ğµ…Í É•©•Ñ¥½¸±•…Ù•Ì4(€€€€€€€€Œ…¸…µ‰¥Õ½ÕÌ½É‘•È©½ÕÉ¹…°Ñ¡…ĞÕ¹¹••ÍÍ…É¥±ä‰±½­Ì±…Ñ•ÈÉ•½Ù•Éä¸4(€€€€€€€¥˜…Í¡}É•Í•ÉÙ•è4(€€€€€€€€€€€Í•±˜¹±•‘•È¹É•Í•ÉÙ”¡¥¹Ñ•¹Ğ¹¥¹Ñ•¹Ñ}¥°¥¹Ñ•¹Ğ¹ÅÑä€¨¥¹Ñ•¹Ğ¹±¥µ¥Ñ}ÁÉ¥”°½¹Ñ•áĞ¹¹½Ü¤4(€€€€€€€ÑÉäè4(€€€€€€€€€€€Í•±˜¹ÍÑ½É”¹Í…Ù•}¥¹Ñ•¹Ğ¡¥¹Ñ•¹Ğ¤4(€€€€€€€•á•ÁĞá•ÁÑ¥½¸è4(€€€€€€€€€€€¥˜…Í¡}É•Í•ÉÙ•è4(€€€€€€€€€€€€€€€Í•±˜¹±•‘•È¹É•±•…Í”¡¥¹Ñ•¹Ğ¹¥¹Ñ•¹Ñ}¥°½¹Ñ•áĞ¹¹½Ü¤4(€€€€€€€€€€€É…¥Í”4(€€€€€€€É•½Éõ=É‘•ÉI•½É¡¥¹Ñ•¹Ğ¤ìÍ•±˜¹É•½É‘Ím¥¹Ñ•¹Ğ¹¥¹Ñ•¹Ñ}¥‘tõÉ•½É4(€€€€€€€Í•±˜¹}ÑÉ…¹Í¥Ñ¥½¸¡É•½É±=É‘•ÉMÑ…Ñ”¹Y1%Q±½¹Ñ•áĞ¹¹½Ü¤ìÍ•±˜¹}ÑÉ…¹Í¥Ñ¥½¸¡É•½É±=É‘•ÉMÑ…Ñ”¹MU	5%QQ%9±½¹Ñ•áĞ¹¹½Ü¤4(€€€€€€€ÑÉäè‰É½­•É}½É‘•É}¥±™¥±±ÌõÍ•±˜¹…‘…ÁÑ•È¹Á±…”¡¥¹Ñ•¹Ğ¤4(€€€€€€€•á•ÁĞA…Á•É=É‘•ÉI•©•Ñ•è4(€€€€€€€€€€€¥˜…Í¡}É•Í•ÉÙ•è4(€€€€€€€€€€€€€€€Í•±˜¹±•‘•È¹É•±•…Í”¡¥¹Ñ•¹Ğ¹¥¹Ñ•¹Ñ}¥°½¹Ñ•áĞ¹¹½Ü¤4(€€€€€€€€€€€Í•±˜¹}ÑÉ…¹Í¥Ñ¥½¸¡É•½É±=É‘•ÉMÑ…Ñ”¹I)Q±½¹Ñ•áĞ¹¹½Ü¤ìÉ•ÑÕÉ¸É•½É4(€€€€€€€¥˜¹½Ğ‰É½­•É}½É‘•É}¥èÉ…¥Í”á•ÕÑ¥½¹	±½­• ‰Á…Á•È‰É½­•È½É‘•È¥‘•¹Ñ¥Ñä¥Ìµ¥ÍÍ¥¹œˆ¤4(€€€€€€€™¥±±ÌõÑÕÁ±”¡™¥±±Ì¤ìÍ••¸õÍ•Ğ ¤ìÙ…±¥‘…Ñ•õmtìÑ½Ñ…°õ•¥µ…° ˆÀˆ¤4(€€€€€€€™½È™¥±±}¥±ÅÕ…¹Ñ¥Ñä±ÁÉ¥”¥¸™¥±±Ìè4(€€€€€€€€€€€ÅÕ…¹Ñ¥Ñäõ}‘•¥µ…°¡ÅÕ…¹Ñ¥Ñä°‰™¥±°ÅÕ…¹Ñ¥Ñäˆ¤ìÁÉ¥”õ}‘•¥µ…°¡ÁÉ¥”°‰™¥±°ÁÉ¥”ˆ¤4(€€€€€€€€€€€¥˜¹½Ğ™¥±±}¥½È™¥±±}¥¥¸Í••¸½ÈÍ•±˜¹ÍÑ½É”¹™¥±±}•á¥ÍÑÌ¡™¥±±}¥¤½ÈÁÉ¥”ğôÀ½ÈÅÕ…¹Ñ¥ÑäğôÀ½ÈÑ½Ñ…°­ÅÕ…¹Ñ¥Ñäù¥¹Ñ•¹Ğ¹ÅÑäèÉ…¥Í”á•ÕÑ¥½¹	±½­• ‰¥¹Ù…±¥½È‘ÕÁ±¥…Ñ”Á…Á•È™¥±°ˆ¤4(€€€€€€€€€€€¥˜±•‘•É}­¹½İ¸…¹Í•±˜¹±•‘•È¹¡…Í}™¥±±}É••¥ÁĞ¡™¥±±}¥¤è4(€€€€€€€€€€€€€€€€Œ=™™±¥¹”Í••‘¥¹œ½ÈÉ•Á±…ä…¸¡…Ù”±•¥Ñ¥µ…Ñ”±•‘•È™¥±±Ì4(€€€€€€€€€€€€€€€€Œ…‰Í•¹Ğ™É½´Ñ¡”½É‘•È©½ÕÉ¹…°¸9•Ù•ÈÉ•½É„™…±Í”%114(€€€€€€€€€€€€€€€€Œ©½ÕÉ¹…°‰•™½É”‘¥Í½Ù•É¥¹œÑ¡¥Ì¥¹‘•Á•¹‘•¹Ğ½±±¥Í¥½¸¸4(€€€€€€€€€€€€€€€É…¥Í”á•ÕÑ¥½¹	±½­• ‰™¥±°¥‘•¹Ñ¥Ñä…±É•…‘ä•á¥ÍÑÌ¥¸Á…Á•È±•‘•ÈìÉ•½¹¥±¥…Ñ¥½¸É•ÅÕ¥É•ˆ¤4(€€€€€€€€€€€€Œ… 1%5%P•á•ÕÑ¥½¸µÕÍĞ¡½¹½ÈÑ¡”Í¥‘”µÍÁ•¥™¥Œ±¥µ¥Ğ°¹½Ğ4(€€€€€€€€€€€€Œµ•É•±ä…Ù•É…”½ÕĞ…¸¥¹Ù…±¥ÁÉ¥”İ¥Ñ „™…Ù½É…‰±”™¥±°¸4(€€€€€€€€€€€€ŒI•©•ĞÑ¡”•¹Ñ¥É”Íå¹Ñ¡•Ñ¥Œ‰…Ñ ‰•™½É”©½ÕÉ¹…°AQ¸4(€€€€€€€€€€€¥˜€¡¥¹Ñ•¹Ğ¹Í¥‘”¥ÌM¥‘”¹	Ud…¹ÁÉ¥”€ø¥¹Ñ•¹Ğ¹±¥µ¥Ñ}ÁÉ¥”¤½È€ 4(€€€€€€€€€€€€€€€¥¹Ñ•¹Ğ¹Í¥‘”¥ÌM¥‘”¹M10…¹ÁÉ¥”€ğ¥¹Ñ•¹Ğ¹±¥µ¥Ñ}ÁÉ¥”4(€€€€€€€€€€€€¤è4(€€€€€€€€€€€€€€€É…¥Í”á•ÕÑ¥½¹	±½­• ‰Á…Á•È™¥±°Ù¥½±…Ñ•ÌÍ¥‘”µÍÁ•¥™¥Œ±¥µ¥ĞÁÉ¥”ìÉ•½¹¥±¥…Ñ¥½¸É•ÅÕ¥É•ˆ¤4(€€€€€€€€€€€Í••¸¹…‘¡™¥±±}¥¤ìÑ½Ñ…°¬õÅÕ…¹Ñ¥ÑäìÙ…±¥‘…Ñ•¹…ÁÁ•¹ ¡™¥±±}¥±ÅÕ…¹Ñ¥Ñä±ÁÉ¥”¤¤4(€€€€€€€€Œ¡•¬Ñ¡”•¹Ñ¥É”É•ÑÕÉ¹•‰…Ñ ……¥¹ÍĞÑ¡”…±É•…‘äÉ•Í•ÉÙ•4(€€€€€€€€Œ…Í €¼½İ¹•Á½Í¥Ñ¥½¸	=I…ÁÁ•¹‘¥¹œ•Ù•¸Ñ¡”™¥ÉÍĞ%11½È4(€€€€€€€€ŒAIQ%0©½ÕÉ¹…°•Ù•¹Ğ¸¸½Ù•Èµ±¥µ¥ĞÍå¹Ñ¡•Ñ¥ŒÉ••¥ÁĞµÕÍĞ±•…Ù”4(€€€€€€€€ŒÑ¡”ÍÕ‰µ¥ÍÍ¥½¸Á•¹‘¥¹œÉ•½¹¥±¥…Ñ¥½¸°¹•Ù•È±…¥´„‘ÕÉ…‰±”™¥±°4(€€€€€€€€Œİ¡¥±”Ñ¡”¥¹‘•Á•¹‘•¹Ğ±•‘•ÈÉ•©•ÑÌ¥Ğ¸4(€€€€€€€¥˜±•‘•É}­¹½İ¸…¹Ù…±¥‘…Ñ•è4(€€€€€€€€€€€¥˜…Í¡}É•Í•ÉÙ•è4(€€€€€€€€€€€€€€€Ñ½Ñ…±}½ÍĞ€ôÍÕ´ 4(€€€€€€€€€€€€€€€€€€€€¡ÅÕ…¹Ñ¥Ñä€¨ÁÉ¥”™½È|°ÅÕ…¹Ñ¥Ñä°ÁÉ¥”¥¸Ù…±¥‘…Ñ•¤°4(€€€€€€€€€€€€€€€€€€€•¥µ…° ˆÀˆ¤°4(€€€€€€€€€€€€€€€€¤4(€€€€€€€€€€€€€€€¥˜Ñ½Ñ…±}½ÍĞ€ø¥¹Ñ•¹Ğ¹ÅÑä€¨¥¹Ñ•¹Ğ¹±¥µ¥Ñ}ÁÉ¥”è4(€€€€€€€€€€€€€€€€€€€É…¥Í”á•ÕÑ¥½¹	±½­• 4(€€€€€€€€€€€€€€€€€€€€€€€€‰Á…Á•È‰ÕäÉ••¥ÁÑÌ•á••½İ¸É•Í•ÉÙ…Ñ¥½¸ìÉ•½¹¥±¥…Ñ¥½¸É•ÅÕ¥É•ˆ4(€€€€€€€€€€€€€€€€€€€€¤4(€€€€€€€€€€€•±¥˜¥¹Ñ•¹Ğ¹Í¥‘”¥ÌM¥‘”¹M10è4(€€€€€€€€€€€€€€€½İ¹•‘}ÅÑä€ô¹•áĞ 4(€€€€€€€€€€€€€€€€€€€€¡Á½Í¥Ñ¥½¸¹ÅÑä™½ÈÁ½Í¥Ñ¥½¸¥¸Í•±˜¹±•‘•È¹Á½Í¥Ñ¥½¹Ì ¤4(€€€€€€€€€€€€€€€€€€€€¥˜Á½Í¥Ñ¥½¸¹Íåµ‰½°€ôô¥¹Ñ•¹Ğ¹Íåµ‰½°¹ÕÁÁ•È ¤¤°4(€€€€€€€€€€€€€€€€€€€•¥µ…° ˆÀˆ¤°4(€€€€€€€€€€€€€€€€¤4(€€€€€€€€€€€€€€€¥˜Ñ½Ñ…°€ø½İ¹•‘}ÅÑäè4(€€€€€€€€€€€€€€€€€€€É…¥Í”á•ÕÑ¥½¹	±½­• 4(€€€€€€€€€€€€€€€€€€€€€€€€‰Á…Á•ÈÍ•±°É••¥ÁÑÌ•á••½İ¹•ÅÕ…¹Ñ¥ÑäìÉ•½¹¥±¥…Ñ¥½¸É•ÅÕ¥É•ˆ4(€€€€€€€€€€€€€€€€€€€€¤4(€€€€€€€É•½É¹‰É½­•É}½É‘•É}¥õ‰É½­•É}½É‘•É}¥ìÍ•±˜¹}ÑÉ…¹Í¥Ñ¥½¸¡É•½É±=É‘•ÉMÑ…Ñ”¹AQ±½¹Ñ•áĞ¹¹½Ü±‰É½­•É}½É‘•É}¥õ‰É½­•É}½É‘•É}¥¤4(€€€€€€€™½È™¥±±}¥±ÅÕ…¹Ñ¥Ñä±ÁÉ¥”¥¸Ù…±¥‘…Ñ•è4(€€€€€€€€€€€É•½É¹™¥±±}¥‘Ì¹…ÁÁ•¹¡™¥±±}¥¤ìÉ•½É¹™¥±±•‘}ÅÑä¬õÅÕ…¹Ñ¥ÑäìÍ•±˜¹}ÑÉ…¹Í¥Ñ¥½¸¡É•½É±=É‘•ÉMÑ…Ñ”¹%11¥˜É•½É¹™¥±±•‘}ÅÑäôõ¥¹Ñ•¹Ğ¹ÅÑä•±Í”=É‘•ÉMÑ…Ñ”¹AIQ%0±½¹Ñ•áĞ¹¹½Ü±™¥±±}¥õ™¥±±}¥±ÅÕ…¹Ñ¥ÑäõÅÕ…¹Ñ¥Ñä±ÁÉ¥”õÁÉ¥”±‰É½­•É}½É‘•É}¥õ‰É½­•É}½É‘•É}¥¤4(€€€€€€€€€€€¥˜±•‘•É}­¹½İ¸è4(€€€€€€€€€€€€€€€Í•±˜¹±•‘•È¹É•½É‘}™¥±° 4(€€€€€€€€€€€€€€€€€€€™¥±±}¥õ™¥±±}¥°¥¹Ñ•¹Ñ}¥õ¥¹Ñ•¹Ğ¹¥¹Ñ•¹Ñ}¥°4(€€€€€€€€€€€€€€€€€€€É•Í•ÉÙ…Ñ¥½¹}¥ô¡¥¹Ñ•¹Ğ¹¥¹Ñ•¹Ñ}¥¥˜…Í¡}É•Í•ÉÙ••±Í”9½¹”¤°4(€€€€€€€€€€€€€€€€€€€Íåµ‰½°õ¥¹Ñ•¹Ğ¹Íåµ‰½°°Í¥‘”õ¥¹Ñ•¹Ğ¹Í¥‘”¹Ù…±Õ”°4(€€€€€€€€€€€€€€€€€€€ÅÕ…¹Ñ¥ÑäõÅÕ…¹Ñ¥Ñä°ÁÉ¥”õÁÉ¥”°…Ğõ½¹Ñ•áĞ¹¹½Ü°4(€€€€€€€€€€€€€€€€¤4(€€€€€€€¥˜…Í¡}É•Í•ÉÙ•…¹É•½É¹ÍÑ…Ñ”¥Ì=É‘•ÉMÑ…Ñ”¹%11è4(€€€€€€€€€€€€ŒÕ±°•á•ÕÑ¥½¸µ…ä½ÍĞ±•ÍÌÑ¡…¸Ñ¡”±¥µ¥ĞµÁÉ¥”É•Í•ÉÙ…Ñ¥½¸¸4(€€€€€€€€€€€€ŒI•ÑÕÉ¸½¹±äÕ¹ÕÍ•…Í ™É½´Ñ¡¥Ì½É‘•È°¹½Ğ™É½´½Ñ¡•È¥¹Ñ•¹ÑÌ¸4(€€€€€€€€€€€Í•±˜¹±•‘•È¹É•±•…Í”¡¥¹Ñ•¹Ğ¹¥¹Ñ•¹Ñ}¥°½¹Ñ•áĞ¹¹½Ü¤4(€€€€€€€É•ÑÕÉ¸É•½É4(€€€‘•˜…¹•°¡Í•±˜°¥¹Ñ•¹Ñ}¥èÍÑÈ°…Ğè‘…Ñ•Ñ¥µ”¤€´ø=É‘•ÉI•½Éè4(€€€€€€€É•½ÉõÍ•±˜¹É•½É‘Ì¹•Ğ¡¥¹Ñ•¹Ñ}¥¤4(€€€€€€€¥˜É•½É¥Ì9½¹”½ÈÉ•½É¹‰É½­•É}½É‘•É}¥¥Ì9½¹”½ÈÉ•½É¹ÍÑ…Ñ”¹½Ğ¥¸í=É‘•ÉMÑ…Ñ”¹AQ±=É‘•ÉMÑ…Ñ”¹AIQ%1ôèÉ…¥Í”á•ÕÑ¥½¹	±½­• ‰½É‘•È…¹¹½Ğ‰”…¹•±±•ˆ¤4(€€€€€€€Í•±˜¹}µÕÑ…Ñ¥½¹}…Ñ”¡É•½É¹¥¹Ñ•¹Ğ°I¥Í­½¹Ñ•áĞ¡…Ğ°…Ğ°É•½É¹¥¹Ñ•¹Ğ¹…±±½İ•‘}Í•ÍÍ¥½¸¤¤ìÍ•±˜¹}…ÁÁ•¹ ‰91}IEUMQˆ±É•½É±…Ğ±‰É½­•É}½É‘•É}¥õÉ•½É¹‰É½­•É}½É‘•É}¥¤ìÍ•±˜¹…‘…ÁÑ•È¹…¹•°¡É•½É¹‰É½­•É}½É‘•É}¥¤ìÍ•±˜¹}ÑÉ…¹Í¥Ñ¥½¸¡É•½É±=É‘•ÉMÑ…Ñ”¹911±…Ğ±‰É½­•É}½É‘•É}¥õÉ•½É¹‰É½­•É}½É‘•É}¥¤4(€€€€€€€¥˜Í•±˜¹±•‘•È¹‰…±…¹” ¤¹ÍÑ…ÑÕÌ€ôô€‰-9=]8ˆ…¹É•½É¹¥¹Ñ•¹Ğ¹Í¥‘”¥ÌM¥‘”¹	Udè4(€€€€€€€€€€€Í•±˜¹±•‘•È¹É•±•…Í”¡¥¹Ñ•¹Ñ}¥°…Ğ¤4(€€€€€€€É•ÑÕÉ¸É•½É4(€€€‘•˜É•Á±…”¡Í•±˜°¥¹Ñ•¹Ñ}¥èÍÑÈ°É•Á±…•µ•¹Ğè=É‘•É%¹Ñ•¹Ğ°½¹Ñ•áĞèI¥Í­½¹Ñ•áĞ¤€´ø=É‘•ÉI•½Éè4(€€€€€€€É•½ÉõÍ•±˜¹É•½É‘Ì¹•Ğ¡¥¹Ñ•¹Ñ}¥¤4(€€€€€€€¥˜É•½É¥Ì9½¹”½ÈÉ•½É¹‰É½­•É}½É‘•É}¥¥Ì9½¹”½ÈÉ•½É¹ÍÑ…Ñ”¹½Ğ¥¸í=É‘•ÉMÑ…Ñ”¹AQ±=É‘•ÉMÑ…Ñ”¹AIQ%1ôèÉ…¥Í”á•ÕÑ¥½¹	±½­• ‰½É‘•È…¹¹½Ğ‰”É•Á±…•ˆ¤4(€€€€€€€¥˜É•Á±…•µ•¹Ğ¹¥¹Ñ•¹Ñ}¥¥¸Í•±˜¹É•½É‘Ì½ÈÍ•±˜¹É•½¹¥±¥…Ñ¥½¸¥Ì9½¹”èÉ…¥Í”á•ÕÑ¥½¹	±½­• ‰É•Á±…•µ•¹Ğ¥¹Ñ•¹Ñ}¥…±É•…‘ä•á¥ÍÑÌ½ÈÉ•½¹¥±¥…Ñ¥½¸¥Ìµ¥ÍÍ¥¹œˆ¤4(€€€€€€€¥˜Í•±˜¹±•‘•È¹‰…±…¹” ¤¹ÍÑ…ÑÕÌ€ôô€‰-9=]8ˆè4(€€€€€€€€€€€€Œ=É¥¥¹…°…¹¹•ÜÉ•Í•ÉÙ…Ñ¥½¹Ì…¹¹½Ğ‰”…Ñ½µ¥…±±äÉ•…ÍÍ¥¹•4(€€€€€€€€€€€€Œ…É½ÍÌ…¸•áÑ•É¹…°‰É½­•ÈÉ•Á±…”…±±‰…¬¸U¹Ñ¥°¥¹‘•Á•¹‘•¹Ğ4(€€€€€€€€€€€€ŒÉ••¥ÁÑÌ½É•½¹¥±¥…Ñ¥½¸•á¥ÍĞ°™…¥°‰•™½É”…¹ä…‘…ÁÑ•ÈµÕÑ…Ñ¥½¸¸4(€€€€€€€€€€€É…¥Í”á•ÕÑ¥½¹	±½­• ‰±•‘•Èµ‰…­•É•Á±…”É•ÅÕ¥É•ÌÉ••¥ÁĞÉ•½¹¥±¥…Ñ¥½¸ˆ¤4(€€€€€€€Í•±˜¹}µÕÑ…Ñ¥½¹}…Ñ”¡É•Á±…•µ•¹Ğ±½¹Ñ•áĞ¤ìÍ•±˜¹ÍÑ½É”¹Í…Ù•}¥¹Ñ•¹Ğ¡É•Á±…•µ•¹Ğ¤ìÍ•±˜¹}…ÁÁ•¹ ‰IA1}IEUMQˆ±É•½É±½¹Ñ•áĞ¹¹½Ü±É•Á±…•‘}‰äõÉ•Á±…•µ•¹Ğ¹¥¹Ñ•¹Ñ}¥¤ì¹•İ}‰É½­•É}½É‘•É}¥õÍ•±˜¹…‘…ÁÑ•È¹É•Á±…”¡É•½É¹‰É½­•É}½É‘•É}¥±É•Á±…•µ•¹Ğ¤ìÍ•±˜¹}ÑÉ…¹Í¥Ñ¥½¸¡É•½É±=É‘•ÉMÑ…Ñ”¹MUAIM±½¹Ñ•áĞ¹¹½Ü±É•Á±…•‘}‰äõÉ•Á±…•µ•¹Ğ¹¥¹Ñ•¹Ñ}¥¤4(€€€€€€€¹•İ}É•½Éõ=É‘•ÉI•½É¡É•Á±…•µ•¹Ğ±=É‘•ÉMÑ…Ñ”¹AQ±¹•İ}‰É½­•É}½É‘•É}¥¤ìÍ•±˜¹É•½É‘ÍmÉ•Á±…•µ•¹Ğ¹¥¹Ñ•¹Ñ}¥‘tõ¹•İ}É•½ÉìÍ•±˜¹}…ÁÁ•¹ ‰AQˆ±¹•İ}É•½É±½¹Ñ•áĞ¹¹½Ü±}ÍÑ…Ñ”õ=É‘•ÉMÑ…Ñ”¹AQ±‰É½­•É}½É‘•É}¥õ¹•İ}‰É½­•É}½É‘•É}¥±É•Á±…•Ìõ¥¹Ñ•¹Ñ}¥¤4(€€€€€€€É•ÑÕÉ¸¹•İ}É•½É4(
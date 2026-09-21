# STOCK RAZOR | Unified Engineering Task Ledger V1.0

Status snapshot: 2026-09-17 JST. Verified canonical `main` at this snapshot: `945bd2d59494c3073f5da903c79fc4b029da72fc`. This document is the existing **single engineering coordination ledger**, proposed by [PR #147](https://github.com/kaku3030/stock-razor/pull/147); #147 is a Draft PR, not a merged ledger or a standalone Issue. Recheck PR heads, main and GitHub evidence at each new run; this snapshot is not a live data feed. Where the source or verification is missing, record `UNKNOWN` rather than extrapolating. The issue board is NOT OPERATIONAL: existing PR conversations provide interim task/report writeback, not automatic cross-chat delivery or wake-up.

## Status and authority

Record `DESIGN`, `IMPLEMENTED`, `PR-HEAD CI`, `INDEPENDENT REVIEW`, `CURRENT-MAIN INTEGRATION`, `PIT/DATA APPROVAL`, `MERGED`, `DEPLOYED`, and `ACCEPTED` separately. An old-head CI/review cannot approve a changed head; a successful PR-head test cannot stand in for merged-tree, live-provider, or authenticated ChatGPT end-to-end evidence. Research-only acceptance never permits trading or production promotion. GitHub comments are coordination evidence, not proof other chats have read them.

User-authorized scope for **this reconciliation only**: edit `docs/ENGINEERING_TASK_LEDGER_V1.md` on existing #147 branch, then verify new exact-head CI and independent review. No other file/PR metadata/branch mutation, issue creation, merge, deployment, credential change, Holdout access, or trade is authorized. This file update creates a NEW #147 head; previously successful CI `35167841421` / Research Radar `35167841398` and the approval anchored to old `2097f9a9a53ad64408dbc7a2acd13f622a00a1ba` are **HISTORICAL ONLY**. New-head checks/re-review must be obtained and recorded independently.

## Exactly four work lanes and ownership

- **Engineering Control Tower (ECT)**: sole engineering coordinator, priority/WIP, owner arbitration, this one ledger, dependencies, evidence review, integration acceptance and concise reporting. Not an additional implementation Owner or a substitute for an independent reviewer.
- **Radar**: sole market/candidate/hypothesis research Owner for A-share, US and global policy, RS, capital persistence, Lifecycle, research Entry Gate and upstream data-semantic acceptance. Delivers evidence to AI Monitor and frozen hypotheses to Quant; no provider runtime or backtester implementation.
- **AI Monitor**: sole production Provider Worker/LiveFeed, Currentness, normalized cache, Portfolio Runtime Truth, continuity/restart, notification and authenticated read-only market-data runtime Owner. Does not rerank Radar candidates.
- **Quant Research Machine**: sole Strategy Lab/backtest/replay, PIT/OOS/holdout governance, experiment registry, counterfactual, costs/delays and validation/performance reporting Owner. No provider runtime or trading authority.

Prior `Main Control & Trading Desk` and combined `Radar / Quant Research` Owner names in the former ledger are historical and must not be used for new work. Harvest/Perception are functions within these lanes, not extra production Owners or a fifth mainline.

## Active tasks: unique owner, canonical evidence, blockers

| Task ID | Sole owner | Canonical coordination / implementation | Verified at snapshot | Open gate and next deliverable |
|---|---|---|---|---|
| **P0 / LEDGER** | Engineering Control Tower | [#147](https://github.com/kaku3030/stock-razor/pull/147); only `docs/ENGINEERING_TASK_LEDGER_V1.md` | OPEN/DRAFT/UNMERGED at pre-edit head `2097f9a`; old-head CI and Research Radar PASS, independent `shucai30` approval on that OLD head only | This document reconciliation is an authorized doc-only change. After commit: fetch NEW exact head, verify newly triggered CI/Radar, request/obtain independent new-head review; current-main integration and merge remain NOT ACCEPTED/NOT AUTHORIZED. Do not invent an Issue board. |
| **RADAR-P0-EVIDENCE** | Radar | Coordination [#147](https://github.com/kaku3030/stock-razor/pull/147), research-only; implementation PR N/A | Both GitHub packets POSTED: [data-semantics for #148](https://github.com/kaku3030/stock-razor/pull/147#issuecomment-5714622866) and [frozen hypothesis for #149](https://github.com/kaku3030/stock-razor/pull/147#issuecomment-5714635696); cross-linked to their owner PRs | Implementation-owner ACK/actual use NOT VERIFIED; `ACCEPTED=NO` pending explicit acknowledgments and mapping. No fresh-market/candidate persistence implied. |
| **P0-A / P2 LIVE DATA** | AI Monitor | Sole implementation [#148](https://github.com/kaku3030/stock-razor/pull/148) | OPEN/DRAFT/UNMERGED head `ed33fee58f3aff99c95a64451705610c28a6a8d0`; PR-head CI `35206850270` PASS and Research Radar `35206850239` PASS; older independent reviews DISMISSED, exact-head approval NOT VERIFIED | Default API has no verified composed long-lived single Provider Owner. Real CN+US provider→normalized 1m→15m/60m→authenticated API, entitlement and separately ChatGPT→Stock Razor E2E NOT PASSED; device last rechecked OFFLINE. Within existing six-path authorization, deliver real single-owner lifecycle/composition and negative-path tests **or** minimum exact additional-path scope request. New-head review, integration, merge, deploy and LIVE all remain closed. |
| **P0-B / P3 HARNESS** | Quant Research Machine | Sole active hardening implementation [#149](https://github.com/kaku3030/stock-razor/pull/149); previously merged substrate [#126](https://github.com/kaku3030/stock-razor/pull/126) is not a second active PR | OPEN/DRAFT/UNMERGED head `e0c651a35fe55428fdcbb4fb0e827276d68b1a3b`; PR-head CI `35168838740` PASS, Radar `35168838666` PASS, `shucai30` APPROVED for this head. [Integration plan delivered](https://github.com/kaku3030/stock-razor/pull/149#issuecomment-5714595064). Main and #149 DIVERGED, filename overlap of intervening three USER_PINNED main-only files with five PR files = NONE, but merged-tree compatibility is UNKNOWN | Old-main artifact `10472531774` from run `35159682596` is recorded capture only; reported 20 captures/20 hashes not independently reaudited here. No fresh current-main artifact, no formal manifest-level PIT approval, no merged-tree CI. [Holdout gate](https://github.com/kaku3030/stock-razor/pull/149#issuecomment-5714690501): runner emits `never_seen_holdout`/overall metrics yet reports `consumes_holdout=false` without demonstrated split/OOS Ledger binding; actual governed holdout exposure UNKNOWN, integrity NOT ACCEPTED. Quant must establish provenance/exposure from metadata (DO NOT inspect protected data), propose minimal fail-closed correction, then request separately scoped file/branch action. Do not tune on or promote current metrics. |
| **P4 / MINIMAL CORE** | Engineering Control Tower (coordination; implementation Owner per approved future slice) | New implementation PR: NONE / UNKNOWN | BACKLOG, no new scope opened | Keep WIP frozen; reuse existing implementations; open only if necessary to unblock P0-A/P0-B and separately authorized. |

## Merged, reusable substrate (not active tasks)

| Scope | Verified status | Reuse boundary |
|---|---|---|
| Radar A3 recorded-fixture #145 | [#145](https://github.com/kaku3030/stock-razor/pull/145) MERGED as `f5ad09409911fc760f39ff1064228610d7bd1fd2` | Existing research fixture substrate; no duplicate PR or production provider authority. |
| Radar A4a/A4b #146 | [#146](https://github.com/kaku3030/stock-razor/pull/146) MERGED as `cc79ce3a9733895160677649f8a43722ed029b85` | Raw-capture/provider-recorded research substrate; does not prove formal PIT approval. |
| AI Monitor Active Watch Universe #129 | [#129](https://github.com/kaku3030/stock-razor/pull/129) MERGED as `30a6391f80649e0be28ed80dbfe4a818309636e8` | Membership semantics only; no live runtime binding. |
| AI Monitor USER_PINNED persistence #133 | [#133](https://github.com/kaku3030/stock-razor/pull/133) MERGED as `945bd2d59494c3073f5da903c79fc4b029da72fc` | Narrow durable pin ownership, not Provider/LiveFeed/Entry Permission. Historical CI FAIL and `NOT_MERGED` rows from an earlier #133 head are stale, not its final state. |
| Quant RS breakout runner #126 | [#126](https://github.com/kaku3030/stock-razor/pull/126) MERGED as `3d117f2929d400eb402edf4d6aa54d2cb1a22a8c` | Research-only executable baseline, NOT the same as validated/approved PIT/OOS results or #149 completion. |

## Unmerged dependency / historical PR inventory (do not duplicate or auto-land)

| Slice | Verified PR state and head | Required boundary |
|---|---|---|
| AI Monitor consumer-intent #130 | [OPEN / UNMERGED](https://github.com/kaku3030/stock-razor/pull/130), head `dc281f527405ff6f1c39619a7bbdc2ed22333402`; reviewer requested, exact-head approval UNKNOWN | Originally stacked on #129; base and current-main integration must be independently adjudicated. |
| LiveFeed consumer ownership #135 | [OPEN / UNMERGED](https://github.com/kaku3030/stock-razor/pull/135), head `9b07d2f86e40b0ed7eb0394dc0097d484ebfd889` | Stacked on #130; shared-consumer ref counting is a prerequisite, not proof of production binding. |
| LiveFeed consumer ingress #138 | [OPEN / UNMERGED](https://github.com/kaku3030/stock-razor/pull/138), head `8f8afa41aa262a16a9969a822e128cdff0293a25` | Stacked on #135; no automatic landing or promotion. |
| Alternative USER_PINNED #131 | [OPEN / UNMERGED](https://github.com/kaku3030/stock-razor/pull/131), head `a24a9bc2c4e8ee8ed5fbbcbcd5c1c69bbb28924b` | Overlaps the purpose of merged #133; retain as historical evidence, do not recreate or close without authorization/owner review. |
| Research/Shadow observation seam #144 | [OPEN / UNMERGED](https://github.com/kaku3030/stock-razor/pull/144), head `f96b9eb7e048be80a6f8cc5557bfaef2cbb9b384` | Assembly-only; not a complete Shadow/LIVE runtime. No landing decision here. |
| Provider read stub #104 / #112 | [#104 OPEN/DRAFT](https://github.com/kaku3030/stock-razor/pull/104) head `e07107b4327d516336797906883762f957faeae5`; [#112 OPEN/DRAFT](https://github.com/kaku3030/stock-razor/pull/112) head `cd9733035756207810ebbf6cda79a30fb436b783` | Fake/stub-only stacked provider reads, not real feed access or the P0-A canonical runtime. Review/current-main integration UNKNOWN. |

## Next evidence and acceptance sequence

1. ECT: verify this doc's NEW #147 exact-head CI/Radar and request independent new-head review; no inherited approvals, no self-approval, no merge without user's separate permission.
2. AI Monitor: acknowledge Radar's packet in #148 and deliver a real sole-runtime Owner implementation or exact-path blocker, then fresh exact-head checks/review. Prove genuine CN/US sample and authenticated ChatGPT E2E independently; no fabricated realtime or public OpenD.
3. Quant: acknowledge Radar's frozen hypothesis in #149, resolve the holdout provenance/report contradiction from metadata without accessing protected Holdout, and distinguish branch-integration, fresh capture, formal PIT approval and performance validation. Any #149 file or branch change requires separate user authorization.
4. Radar: wait for owner acknowledgment; if missing, correct only research evidence mapping under existing #147/#148/#149 comments, not provider or backtester code.
5. All lanes: submit actual deltas, exact head and evidence to existing GitHub PR threads. ECT reads on demand. `GITHUB_WRITEBACK=VERIFIED_FOR_REPORTS`; other ChatGPT chats waking automatically = `NOT_VERIFIED`. No new Issue/PR or parallel ledger.

**Global gates at this snapshot:** `#147_DOC_RECONCILIATION=AUTHORIZED_IN_PROGRESS | #148_LIVE_E2E=NOT_PASSED | #149_HOLDOUT_INTEGRITY=UNKNOWN_NOT_ACCEPTED | #149_PIT_APPROVAL=NOT_PASSED | MERGE=NO | DEPLOY=NO | PRODUCTION_PROMOTION=NO | TRADE=NO`.

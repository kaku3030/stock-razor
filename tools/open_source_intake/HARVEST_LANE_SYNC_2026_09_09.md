# Open-Source Intake / Harvesting Lane — Sync 2026-09-09

Status: ACTIVE SUB-LANE under the Stock Razor / Radar program.

## CURRENT AUTHORITATIVE STATUS

Engineering truth is taken from current GitHub state and exact-head validation. Historical statements below do not override this section.

- **PR #42** | branch `feature/live-feed-provider-worker-v0.1-slice-a` | head `0d5f748cf9f52e3b8d6a2eb985c4db1750e88e8f` | Slice A IMPLEMENTED | CI PASS | Research Radar Tests PASS | independent review ACCEPTED | Harvest promotion state `VALIDATING — ACCEPT` | blocker: Slice B NOT AUTHORIZED / not implied.
- **PR #41** | branch `harvest/futu-kline-timestamp-semantics-p0` | head `cd1f0f0a1dbea020b8aa1064707b9dd05736ab5d` | evidence report + bounded live/snapshot/analyzer tooling IMPLEMENTED | **CI PASS + Research Radar Tests PASS on this exact head** | current exact-head independent review PENDING after tooling changes; prior review on `7ccab96f...` is HISTORICAL ONLY | provider evidence still UNKNOWN/PARTIALLY_VERIFIED by fact | positive 15m/1h Currentness timing freeze BLOCKED pending controlled US K_15M/K_60M OpenD evidence.
- **PR #40** | branch `harvest/a-share-provider-lineage-a0` | head `54250eba6eb64362ea8ac55c383ad6a589ca59ad` | A0.1 + A0.2 IMPLEMENTED (provider lineage identity + reconciliation-safe independence view) | CI PASS | Research Radar Tests PASS | Harvest promotion state VALIDATING | no routing/currentness/decision-weighting promotion implied.
- **PR #31** | branch `harvest/open-source-ledger-v0.1` | this document is the durable Harvest synchronization surface. Cross-Window Sync Constitution V0.1 applies. The branch now also contains `A_SHARE_INTRADAY_15M_1H_CAPABILITY_TRUTH_2026_09_09.md`; any new #31 head requires its own exact-head validation.

### STATUS DRIFT corrections
- Historical Provider Worker text saying implementation had not started is obsolete after PR #42; retained only as historical process context.
- Historical A-share PR #40 head `e4a8c5a3...` is obsolete after A0.2; current head is `54250eba...` and has its own exact-head green CI.
- Historical PR #41 head `7ccab96f...` had green CI and accepted review. Newer evidence-tooling commits moved the head to `cd1f0f0a...`; this new head now has its own CI + Research Radar PASS, while the old independent review remains historical until refreshed.

## Coordination rule
- This workstream is the **Open-Source Intake / Harvesting Lane**.
- Peer sub-lane: **Architecture & Promotion Control Tower**.
- Both report into the Radar main engineering line / 总工程.
- Harvest Lane owns external discovery, screening, gap analysis, harvesting, defect audit, hardening candidates, adversarial validation evidence, and promotion-ready handoff packages.
- Harvest Lane does **not** unilaterally reopen frozen architecture or promote work to SHADOW/CORE.
- Architecture/Promotion decisions remain governed by the Control Tower and Radar main line.
- Durable synchronization should be written to shared GitHub governance/evidence surfaces so all lanes read the same source of truth rather than rely on conversational memory.

## Cross-lane sharing authorization
- The user has explicitly authorized the Radar main line, Harvest Lane, and Architecture & Promotion Control Tower to actively share, retrieve, reuse, cite, and synchronize project material without per-item approval.
- This includes project-relevant code, tests, evidence, provider semantics, research notes, frozen contracts, review findings, PR state, CI state, defects, fixtures, harvest candidates, validation artifacts, implementation briefs, and promotion-readiness evidence.
- Default behavior is **share-first / reuse-first**, not ask-first.
- Sharing does not transfer promotion authority or expand frozen scope.

## Current Harvest outputs

### LiveFeed / provider reliability
- PR #30 — stale/foreign ProviderEvent identity relevance repair; automated gates passed on its validated exact head.
- PR #32 — Hypothesis state-machine testing for LiveFeed invariants; automated gates passed on its validated exact head.
- Network-fault audit completed; existing localhost TransportProxy is sufficient for current cut/restore P0, so Toxiproxy remains deferred.
- Blocking-provider-call audit completed; stdlib ProcessPoolExecutor rejected as a strict hard-timeout boundary.
- Provider Worker Supervisor V0.1 reached DESIGN:FROZEN after staged adversarial reviews.
- PR #42 now implements authorized Slice A contracts/config only. Slice B remains outside current authorization.

### Futu K-line timestamp semantics P0
- PR #41 remains evidence-only; no production controller/adapter/currentness code is changed.
- Official Futu docs still do not establish K_15M/K_60M start-vs-end semantics or US K_60M alignment.
- Closure tooling now includes:
  1. bounded live callback capture;
  2. independently bounded current/history RPC capture;
  3. explicit `history|current|both` operation selection;
  4. explicit historical trade-date selection for half-day evidence;
  5. offline sequence analysis with first/last keys, consecutive gaps, non-nominal final-gap reporting, and no automatic semantic promotion.
- A completed official exchange early-close date such as 2025-11-28 can be used for history-only provider observation; exchange-calendar evidence selects the test date but does not define Futu bar construction.
- Exact head `cd1f0f0a...`: CI PASS + Research Radar Tests PASS. Independent review must be refreshed on this exact head before review status advances.
- Currentness timing freeze remains BLOCKED until real US K_15M/K_60M provider evidence exists.

### Data Reliability
- PR #35 — malformed provider numerics become explicit Health evidence instead of silent/coerced success; automated gates passed on its validated exact head.
- PR #36 — stale-good-health revocation candidate remains stacked / requires independent validation before promotion.
- Currentness/Continuity audit found the intraday false-green risk: same trading date does not prove current progress.

### Strategy Validation
- PR #38 — Radar-native temporal leakage / startup-history audit harvested from Freqtrade methodology without GPL source coupling; automated gates passed on exact head.

### A-share provider lane
- A-share is a first-class Harvest track.
- Existing Stock Razor/upstream DSA already contains a mature multi-source provider layer; do not rebuild it from zero.
- PR #40 A0.1 freezes source/adapter/upstream lineage identity.
- PR #40 A0.2 adds reconciliation-safe upstream independence grouping without provider reordering, fallback mutation, Health/Currentness mutation, or decision weighting.
- New durable audit: `A_SHARE_INTRADAY_15M_1H_CAPABILITY_TRUTH_2026_09_09.md`.
- Current capability conclusion: external/provider 15m/1H support exists in multiple paths, but current `DataCapabilityService` and admitted Radar adapters do **not** expose `kline.15m` / `kline.1h` for CN providers.
- Evidence classifications:
  - Efinance: upstream `klt=15/60` capable; current Radar adapter hardcodes daily `klt=101`; Eastmoney lineage.
  - AkShare: external Eastmoney minute interfaces support 15/60; current Radar adapter uses daily history paths; Eastmoney lineage.
  - PyTDX: underlying TDX categories include 15m/1h; current Radar adapter hardcodes daily category 9.
  - mootdx: external TDX wrapper candidate supports 15m/1h bars; not an approved Radar dependency/admitted capability.
  - Tushare: official realtime/history minute services expose 15m/60m with explicit minute entitlement; current Radar adapter does not expose intraday K-line capability.
  - TickFlow: current Radar adapter requests daily `period="1d"`; authoritative external intraday capability remains UNKNOWN in this audit.
  - BaoStock: external 15/60 historical minute capability; current Radar adapter hardcodes daily; historical/backfill candidate rather than live Currentness primary.
- Permanent distinction: `EXTERNAL_CAPABLE != RADAR_IMPLEMENTED != CURRENTNESS_VERIFIED`.
- Key remaining work: provider-semantic evidence for timestamp boundaries, forming bars, lunch break, close, suspension/zero-trade, units/adjustment, entitlement, and blocking behavior before any Currentness authority is admitted.

## Next Harvest priorities
1. Obtain/refesh independent review of PR #41 exact head `cd1f0f0a...`; execute/ingest controlled US Futu K_15M/K_60M provider evidence when OpenD evidence is available.
2. Turn the A-share 15m/1H truth audit into a candidate normalized capability contract shape for Control Tower review — **design/evidence only, no routing implementation yet**.
3. Continue provider-specific A-share semantics audit, prioritizing independent lineages (Tushare and TDX) plus Eastmoney cross-check while avoiding false independence between Efinance and AkShare EM.
4. Continue Currentness / Continuity / RecoveryCandidate harvest against frozen LiveFeed contracts.
5. Independently validate stacked Data R2 after its base is stable.
6. Keep Control Tower/main line informed of architecture-impacting findings before any implementation exceeds frozen boundaries.

## Handoff truth
Harvest produces evidence and bounded adaptations. Promotion authority remains outside this lane.

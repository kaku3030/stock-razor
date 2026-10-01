# Open-Source Intake — A-share Data Provider Harvest Batch 2026-09-09

Status: RESEARCH / GAP-ANALYSIS / ADAPTATION LEDGER. Non-production.

## Goal

Make A-share market-data providers a first-class Stock Razor Foundation concern without creating a new provider framework where mature implementation already exists.

## Key discovery

The upstream DSA implementation already contains a mature multi-source A-share layer, including Efinance, AkShare, Tencent, PyTDX, BaoStock, Tushare, TickFlow and related routing/fallback tests. Stock Razor also retains provider-capability definitions and scenario-aware routing concepts.

Decision:

> **Do not rebuild the A-share provider framework from zero. Harvest the existing mature implementation, then repair only gaps against Radar frozen invariants.**

## Candidate disposition

- **AKShare:** `ADAPT / TEST-REUSE`; broad coverage, but library identity is not upstream independence identity.
- **Efinance:** `ADAPT`; useful Eastmoney path, lineage-linked with other Eastmoney-backed routes.
- **Tencent / AkShare Tencent:** `ADAPT`; current realtime token and direct daily/index fetcher must not share one ambiguous identity axis.
- **PyTDX / TDX:** `ADAPT / METHOD HARVEST`; useful fallback/protocol ideas, archived upstream and wall-clock cooldown patterns require caution.
- **BaoStock:** `ADAPT / TEST-REUSE` for history/backfill/cross-check, not realtime primary.
- **Tushare:** `ADAPT` subject to explicit entitlement/rate-limit/latency/cost metadata.
- **TickFlow:** `ADAPT`; existing optional provider with useful capability handling, still subject to Radar normalization/currentness rules.

## Proven gaps against Radar Foundation invariants

1. **Adapter identity != upstream lineage.** Multiple wrappers over one external family must not be double-counted.
2. **Malformed != missing.** Dirty non-empty values must not collapse into ordinary missing evidence.
3. **TTL != Currentness.** Wall-clock age is diagnostic input, not authoritative LIVE/currentness qualification.
4. **Monotonic timing required for elapsed/deadline semantics.** Some legacy breaker/cooldown paths use wall-clock time.
5. **Capability vocabulary incomplete for Radar.** Explicit 15m, 1H, calendar/session-shape, corporate-action and point-in-time fundamental capabilities are still needed.

## A0.1 — Realtime provider lineage identity

Draft PR #40 introduced immutable `RealtimeSourceLineage` records separating:

- `source_token`;
- `adapter_id`;
- `upstream_lineage_id`;
- `endpoint_id`;
- markets.

Examples:

- `efinance` -> adapter `efinance`, upstream `eastmoney`;
- `akshare_em` -> adapter `akshare`, upstream `eastmoney`;
- `akshare_sina` -> adapter `akshare`, upstream `sina`;
- `akshare_qq` / `tencent` -> adapter `akshare`, upstream `tencent`, same endpoint identity.

Anti-shrink tests require exact coverage of admitted CN realtime source tokens.

## A0.2 — Reconciliation-safe upstream lineage view

PR #40 now also contains:

`src/services/a_share_reconciliation_lineage.py`

Purpose:

- consume an **already selected / ordered** realtime route;
- expose shared upstream lineage without changing selection;
- preserve route position;
- group independent evidence by `upstream_lineage_id`;
- leave unknown lineage visible but `independence_eligible=False`;
- assign no decision weight and perform no I/O/Health/Currentness mutation.

Permanent invariants/tests:

- `efinance + akshare_em` => one Eastmoney independence group;
- `tencent + akshare_qq` => one Tencent independence group;
- unknown lineage receives no fabricated independent identity;
- route order before/after lineage inspection remains unchanged;
- existing `DataCapabilityService` providers/datasets/priorities/warnings remain unchanged after lineage inspection;
- duplicate/malformed route tokens fail closed;
- source/group outputs contain no numeric decision-weight field;
- explicit governance says `decision_weighting = NONE`.

Research Radar workflow has explicit path triggers and pytest execution for A0.1/A0.2 plus the existing DataCapability suite.

## Current promotion truth

- Previous A0.1 exact head had Research Radar Tests + repository CI PASS.
- A0.2 changed the PR head, so that earlier green status is historical only.
- Current A0.2 exact head must pass its own workflows before current-head `VALIDATING` may be claimed.
- PR remains Draft and does not imply SHADOW/CORE.

## Next A-share Harvest steps

1. Validate the exact A0.2 head.
2. **A0.3 only after A0.2 validation:** add an ultra-thin, additive, read-only `DataCapabilityService` exposure of the existing lineage/reconciliation view. Do not modify routing to achieve the exposure.
3. Build explicit capability inventory for `bars.15m`, `bars.1h`, trading calendar/session shape, corporate actions and point-in-time fundamentals.
4. Audit intraday timestamp/currentness semantics provider-by-provider before granting currentness authority.
5. Keep historical/backfill and realtime authority roles separate.

## Governing rule

> Different wrappers over one upstream do not become independent evidence merely because they have different Python class names.

Harvest work remains Foundation-compatible: identity / evidence / test / CI, no auto-trading or strategy-scope expansion.

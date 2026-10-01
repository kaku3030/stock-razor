# A-share Provider Lineage A0 — Freeze 2026-09-09

Status: DESIGN / IDENTITY CONTRACT FROZEN FOR A0.1 + A0.2.

## Scope

A0 freezes only provider identity and reconciliation-independence metadata for currently admitted CN realtime source tokens. It does not define provider quality, Currentness, routing, fallback, voting weights or trading behavior.

## A0.1 identity axes

Every admitted CN realtime source token must have explicit:

- `source_token` — runtime/config route token;
- `adapter_id` — Stock Razor code path/adapter family;
- `upstream_lineage_id` — external upstream data family used for independence/reconciliation semantics;
- `endpoint_id` — Radar semantic endpoint identifier;
- `markets` — supported market scope for this identity record.

These axes are deliberately not interchangeable.

Examples:

- `efinance`: adapter `efinance`, upstream `eastmoney`;
- `akshare_em`: adapter `akshare`, upstream `eastmoney`;
- `akshare_sina`: adapter `akshare`, upstream `sina`;
- `akshare_qq` and realtime token `tencent`: adapter `akshare`, upstream `tencent`, endpoint `akshare.tencent_spot`.

The separate `TencentFetcher` daily/index implementation is not the identity of the realtime token `tencent`.

## A0.2 reconciliation-independence rules

### Independence unit

For CN realtime reconciliation, the identity unit is:

`upstream_lineage_id`

This is an identity/de-duplication rule, not a quality score or decision weight.

### Shared-upstream invariant

Two or more source tokens that map to the same `upstream_lineage_id` do not become multiple independent observations solely because they use different adapters or aliases.

Examples:

- `efinance + akshare_em` => one Eastmoney independence group;
- `tencent + akshare_qq` => one Tencent independence group.

### Unknown-lineage fail-closed rule

A source token with unknown/unregistered lineage:

- remains visible in diagnostics/evidence;
- receives no fabricated `upstream_lineage_id`;
- has `independence_eligible = False`;
- cannot be counted as a new independent source until lineage is registered/reviewed.

### Route authority boundary

The reconciliation lineage view consumes an existing route. It must never:

- reorder provider tokens;
- add/remove a provider;
- decide fallback;
- perform a provider/network call;
- mutate Health/Currentness;
- assign numeric/compensatory decision weights.

Explicit governance field:

`decision_weighting = NONE`

## Anti-shrink / validation requirements

1. A0.1 lineage manifest exactly matches currently admitted `_CN_REALTIME_SOURCES`.
2. Every manifest key equals embedded `source_token`.
3. Manifest and records are immutable/read-only.
4. Output is deterministic, JSON-ready and secret-free.
5. Eastmoney wrapper paths are proven non-independent.
6. Tencent realtime aliases are proven non-independent and not confused with `TencentFetcher`.
7. Unknown lineage is fail-closed for independence.
8. Reconciliation view preserves existing route order.
9. Calling the view does not mutate existing `DataCapabilityService` providers/datasets/priorities/warnings.
10. Malformed/duplicate route inputs fail closed.
11. Source/group outputs contain no numeric decision-weight field.
12. Research Radar CI must both trigger on A0 source/test paths and explicitly execute the A0 tests.

## Non-scope

- provider score/ranking changes;
- `REALTIME_SOURCE_PRIORITY` changes;
- provider health aggregation;
- Currentness/staleness semantics;
- reconciliation numeric thresholds;
- network/provider calls;
- intraday bar implementation;
- trading/strategy/AI logic;
- new dependencies.

## Promotion boundary

A0 may be described as `VALIDATING` only when its current exact head passes the repository's current automated gates. Passing A0 does not authorize SHADOW/CORE or a reconciliation decision policy.

Future A0.3 may expose this metadata through `DataCapabilityService` as an additive read-only surface after A0.2 validation. That exposure must not couple lineage identity to provider selection.

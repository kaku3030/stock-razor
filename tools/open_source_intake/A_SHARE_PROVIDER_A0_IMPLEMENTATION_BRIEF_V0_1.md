# A-Share Provider A0 — Implementation Brief V0.1

Status: **SLICE SPEC — FROZEN FOR A0 IMPLEMENTATION**
Scope: Foundation / DATA-SCHEMA / TEST only.

## Goal

Make A-share realtime source identity unambiguous without changing provider routing, provider priority, network behavior, Data Health decisions, or trading/analysis outputs.

A0 addresses one proven modeling ambiguity:

> one current `source` token can conflate the Stock Razor adapter with the actual upstream data family.

Examples:

- `akshare_em` = AkShare adapter + Eastmoney upstream;
- `efinance` = Efinance adapter + Eastmoney-oriented upstream;
- `tencent` realtime token is currently represented through the AkShare realtime family, while `TencentFetcher` separately exists for daily/index direct routes.

Without explicit lineage, reconciliation can incorrectly treat two wrappers over one upstream as independent evidence.

## Allowed changes

1. Add an immutable realtime-source lineage definition type to `src/services/data_capability_service.py` or a narrowly scoped sibling schema module.
2. Define additive metadata for each current CN realtime token:
   - `source_token`
   - `adapter_id`
   - `upstream_lineage_id`
   - `endpoint_id`
   - `markets`
3. Expose this information additively from the read-only Data Capability overview, preferably as a top-level `source_lineage` or equivalent clearly non-health field.
4. Add focused tests to existing `tests/test_data_capability_service.py` or one dedicated sibling test file.
5. Update focused CI enumeration only if repository CI requires manual test listing.

## Explicitly forbidden in A0

- changing `REALTIME_SOURCE_PRIORITY` behavior;
- changing any fetcher priority;
- adding/removing a provider;
- changing a circuit-breaker threshold;
- changing failover behavior;
- changing quote normalization;
- changing Currentness/stale logic;
- replacing PyTDX;
- adding mootdx or another dependency;
- adding live provider calls to tests;
- changing Strategy/Signal/AI behavior;
- changing auto-trading scope;
- treating lineage metadata as provider health.

## Required lineage entries

A0 must cover every token currently admitted by `_CN_REALTIME_SOURCES`.

Candidate mapping:

| source_token | adapter_id | upstream_lineage_id | endpoint_id |
| --- | --- | --- | --- |
| `efinance` | `efinance` | `eastmoney` | `efinance.realtime_quote` |
| `akshare_em` | `akshare` | `eastmoney` | `akshare.eastmoney_spot` |
| `akshare_sina` | `akshare` | `sina` | `akshare.sina_spot` |
| `akshare_qq` | `akshare` | `tencent` | `akshare.tencent_spot` |
| `tencent` | `akshare` | `tencent` | `akshare.tencent_spot` |
| `tushare` | `tushare` | `tushare` | `tushare.realtime_quote` |
| `tickflow` | `tickflow` | `tickflow` | `tickflow.realtime_quote` |

The `tencent` / `akshare_qq` alias relationship must be explicit, not hidden.

If implementation audit proves a different current execution path for a token, correct the table before code lands; do not preserve a known-wrong mapping just because it is written here.

## Schema invariants

A0-LIN-01. Every `_CN_REALTIME_SOURCES` token has exactly one lineage definition.

A0-LIN-02. No lineage definition exists for an unknown source token without an explicit capability entry.

A0-LIN-03. `adapter_id` identifies the Stock Razor code path, not the external vendor brand.

A0-LIN-04. `upstream_lineage_id` identifies the external source family used for independence/reconciliation reasoning.

A0-LIN-05. Two source tokens with the same `upstream_lineage_id` must not automatically count as independent corroboration.

A0-LIN-06. `endpoint_id` is a stable Radar semantic identifier, not a promise that an external URL/host will never change.

A0-LIN-07. Lineage metadata is descriptive only and cannot upgrade `unknown/degraded/unavailable` provider or dataset status.

A0-LIN-08. No secret, API key, host credential, token or account information appears in lineage output.

A0-LIN-09. Existing Data Capability response fields retain their current meaning; A0 is additive.

A0-LIN-10. Provider-level identity remains separate from realtime-subsource identity. `TencentFetcher` daily/index capability must not be silently rewritten merely because realtime `tencent` currently routes via the AkShare realtime family.

## Required tests

At minimum:

1. every `_CN_REALTIME_SOURCES` token is represented exactly once;
2. `efinance` and `akshare_em` have different `adapter_id` but same Eastmoney lineage;
3. `akshare_qq` and `tencent` expose the same Tencent upstream lineage and alias-compatible endpoint identity;
4. `tencent` realtime token does not claim `adapter_id=tencent_direct` unless the audited runtime path actually changes;
5. TickFlow/Tushare expose their own upstream lineage;
6. output remains deterministic regardless of fetcher runtime status;
7. lineage metadata contains no configured secrets;
8. existing `quote.realtime` quality/fallback tests remain unchanged and pass;
9. an anti-shrink test verifies the lineage definition key set equals the admitted CN realtime source token set.

## Exit Criteria

A0 is complete only when:

- schema is immutable/static;
- anti-shrink test passes;
- existing Data Capability tests pass;
- repository CI passes on exact head;
- no runtime routing diff exists;
- no dependency was added;
- PR remains DATA/SCHEMA/TEST scope.

Promotion after automated validation: `ADAPTED -> VALIDATING` only. No SHADOW/CORE meaning is implied because A0 carries no live provider behavior.

## Next slice after A0

A1 may address malformed-vs-missing normalization and monotonic cooldown semantics, but A0 must not pre-implement A1.

## Governing sentence

> Before Radar can compare two data sources, it must know whether they are actually two sources.

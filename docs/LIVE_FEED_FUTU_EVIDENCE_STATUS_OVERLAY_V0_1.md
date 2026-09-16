# Live Feed V0.1 — Futu Evidence Status Overlay

Status: PROVIDER-EVIDENCE STATUS OVERLAY — non-normative.

This file exists to resolve a documented evidence-status drift without changing the frozen provider-neutral architecture in `LIVE_FEED_RELIABILITY_CONTRACT_V0_1.md` Sections 1–20/22.

## Authority rule

`docs/LIVE_FEED_RELIABILITY_CONTRACT_V0_1.md` Section 21 explicitly names
`tools/provider_semantics/futu/FUTU_SEMANTIC_CONTRACT_V0_1.md` as the authoritative provider-specific evidence source.

Therefore, where Section 21's historical `Explicitly unresolved` snapshot conflicts with the newer Futu Semantic Contract, the newer evidence registry controls **provider-evidence status only**. It does not change any frozen invariant or promote any controller capability to implemented/validated.

## Drift found on 2026-09-09

The frozen contract's Section 21 still records:

- F15 as unresolved;
- F17 as never observed;
- F18 as untestable without F17;
- auto-resubscribe as source-predicted but not behaviorally observed;
- F04 as unresolved.

The authoritative Futu evidence registry now records Wave 2 as CLOSED and has newer evidence:

| Item | Current evidence status | Scope discipline |
|---|---|---|
| F15 — cross-reconnect ProgressIdentity | `PARTIALLY_VERIFIED` | Transport-vs-context identity verified; tested HK K_1M cross-reconnect ordering verified within tested scope; QUOTE ProgressIdentity remains unresolved/insufficient. |
| F17 — reconnect catch-up behavior | `VERIFIED — TESTED SCOPE` | Three tested active-session reconnect cycles for HK.00700 resumed at current/future K_1M progress; missed intervals were not replayed in those runs. This is not a universal provider guarantee. |
| F18 — replay/backfill distinguishability | `VERIFIED_NEGATIVE_OBSERVATION — TESTED SURFACE` | No authoritative replay/backfill marker was observed in the inspected QUOTE/K_1M SDK/payload surface. This does not prove no such marker exists anywhere. |
| AUTO_RESUBSCRIBE | `VERIFIED — TESTED SCOPE` | Across 3/3 tested reconnect cycles, QUOTE and K_1M push resumed without a manual post-restore `subscribe()` call. SDK resubscribe success is still not Radar Recovery or LIVE qualification. |
| F04 — DeliveryMode / entitlement evidence | `OPEN P0` | Remains the sole open P0 in the current Wave 2 evidence registry. No authoritative REALTIME/DELAYED evidence has been established. |

## Non-negotiable implications

1. `SDK transport reconnect != controller recovery != LIVE` remains unchanged.
2. Auto-resubscribe is provider mechanics/evidence, never sufficient LIVE proof.
3. F17's tested `DIRECT_CURRENT_ONLY` behavior must not be generalized into `Futu never replays`.
4. F18 forbids timing heuristics from manufacturing REALTIME/REPLAY/BACKFILL provenance where authoritative provenance is absent.
5. K_1M tested progress semantics must not be generalized to QUOTE; QUOTE `data_time` remains an insufficient unique ProgressIdentity.
6. F04 remains unresolved, so `DeliveryMode.UNKNOWN` cannot be optimistically promoted.

## Update rule

Any future Futu evidence wave that changes F15/F17/F18/AUTO_RESUBSCRIBE/F04 status must update:

1. `tools/provider_semantics/futu/FUTU_SEMANTIC_CONTRACT_V0_1.md` first, with raw/source evidence and confidence wording;
2. this overlay in the same change set or a follow-up evidence-sync change;
3. any implementation only through the normal Radar contract/validation/promotion gates.

A provider-evidence status change is not, by itself, a design change or production-capability promotion.

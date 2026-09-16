# AI Monitor Active Watch Runtime V0.1

Status: implementation contract for the #129 follow-up slice.

## Ownership

`Active Watch Universe = PORTFOLIO ∪ RADAR ∪ USER_PINNED`.

- Portfolio remains the position-truth owner.
- Radar remains the candidate discovery/ranking owner.
- AI Monitor owns active-watch membership/runtime reconciliation.
- Existing LiveFeed remains the only production subscription runtime.
- This contract does not grant Entry Permission or trading/execution authority.

## Durable USER_PINNED truth

User pins survive AI Monitor restart. Persistence is applied before in-memory membership changes. Corrupt or unreadable durable truth fails closed rather than silently dropping pins. Removing a user pin removes only the `USER_PINNED` source; Portfolio/Radar reasons are unaffected.

V0.1 uses a dedicated atomic JSON file so this slice does not expand the shared production database schema. AI Monitor is the single writer for that file.

## LiveFeed reconciliation

`WatchUniverseLiveFeedBridge` maps active watch identities to existing `SemanticStreamKey` values and enqueues desired-state changes through `LiveFeedController.request_add_desired` / `request_remove_desired`.

Rules:

1. Remove expired bridge-managed keys before adding new ones.
2. Queue rejection must not be recorded as successful reconciliation.
3. The bridge may remove only keys it owns; unrelated LiveFeed desired subscriptions are untouched.
4. Missing market bindings and controller/provider mismatches fail closed.
5. A fresh runtime re-adds the full desired watch universe.
6. Radar candidates do not need to be portfolio positions to enter the LiveFeed desired set.

## Explicit non-goals

This slice does not create a second Provider Worker, LiveFeed runtime, market-data adapter, Radar, Entry Permission engine, broker path, or execution path. It does not change provider routing, currentness semantics, or production promotion state.

Production bootstrap/startup wiring is a separate reviewable slice after exact-head CI and independent review.

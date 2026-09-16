# AI Monitor Active Watch Runtime V0.1

Status: durable USER_PINNED follow-up to the Active Watch Universe contract.

## Ownership

`Active Watch Universe = PORTFOLIO ∪ RADAR ∪ USER_PINNED`.

- Portfolio remains the position-truth owner.
- Radar remains the candidate discovery/ranking owner.
- AI Monitor owns active-watch membership and USER_PINNED persistence.
- Existing LiveFeed remains the only production subscription runtime.
- This contract does not grant Entry Permission or trading/execution authority.

## Durable USER_PINNED truth

User pins survive AI Monitor restart. Persistence is applied before in-memory membership changes. Corrupt or unreadable durable truth fails closed rather than silently dropping pins. Removing a user pin removes only the `USER_PINNED` source; Portfolio/Radar reasons are unaffected.

V0.1 uses a dedicated atomic JSON file so this slice does not expand the shared production database schema. AI Monitor is the single writer for that file.

## LiveFeed boundary: blocked until consumer ownership exists

The existing `DesiredSubscriptionRegistry` is keyed by `SemanticStreamKey` but is not consumer/source-aware. Therefore an AI Monitor caller cannot safely translate its own watch removal into `LiveFeedController.request_remove_desired()`: the same semantic stream may still be required by another consumer.

This slice deliberately performs **no LiveFeed desired-subscription mutation**. Runtime binding remains fail-closed until the existing LiveFeed ownership boundary provides auditable consumer/reference semantics. That prerequisite must be implemented and tested in the existing LiveFeed runtime rather than by creating a second subscription reconciler.

## Explicit non-goals

This slice does not create a second Provider Worker, LiveFeed runtime, market-data adapter, Radar, Entry Permission engine, broker path, or execution path. It does not change provider routing, currentness semantics, or production promotion state.

Production bootstrap/startup wiring is a separate reviewable slice after consumer ownership/reference semantics, exact-head CI, and independent review.

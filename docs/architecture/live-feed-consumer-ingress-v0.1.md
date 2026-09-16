# LiveFeed consumer-bound controller ingress V0.1

This slice connects the existing `LiveFeedController` request boundary to the
consumer/reference ownership API already provided by its single
`DesiredSubscriptionRegistry`.

## Boundary

- `request_add_desired_for_consumer(key, consumer_id)` and
  `request_remove_desired_for_consumer(key, consumer_id)` enqueue intent only.
- `process_pending()` remains the only path that mutates authoritative state.
- The controller passes the explicit consumer ID to the existing registry; it
  does not create a second registry, runtime, provider worker, adapter, or
  reconciler.
- Empty, whitespace-only, and non-string consumer IDs fail closed before
  enqueue. The old request methods remain isolated to `LEGACY_DEFAULT`.

## Revision and command semantics

The registry's provider-facing `revision` changes only when the first consumer
adds a stream or the last consumer releases it. Adding or removing a
non-final consumer changes only `ownership_revision`; it does not create a
provider subscribe/unsubscribe transition and does not invalidate a command
whose `desired_registry_revision` still describes the provider-facing intent.

New-incarnation behavior remains the existing explicit legacy
`request_readd_incarnation()` contract and is not widened by this slice.

## Scope exclusions

Provider routing/currentness, Entry Permission, broker/execution, production
bootstrap, promotion, and merge are unchanged and remain outside this slice.

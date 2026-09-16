# LiveFeed Consumer Ownership V0.1

Status: prerequisite contract for AI Monitor runtime binding.

## Problem

`SemanticStreamKey` identifies provider-facing stream intent, not the consumer that needs it. A key-only desired registry allows one consumer to remove a stream still required by another consumer.

## V0.1 semantics

The existing `DesiredSubscriptionRegistry` remains the single authoritative desired-intent registry. It now records stable consumer IDs per semantic stream.

- First consumer add: create provider-facing desired intent.
- Additional consumer add: ownership-only change; do not bump provider-facing `revision`.
- Non-last consumer removal: ownership-only change; keep provider-facing desired intent.
- Last consumer removal: remove provider-facing desired intent.
- Consumer membership changes advance a separate `ownership_revision`.
- Legacy `add_desired` / `remove_desired` calls are mapped to `LEGACY_DEFAULT`, so a legacy removal cannot delete another consumer's reference.
- Re-add/new-incarnation preserves other consumer references.

This separation prevents consumer-only bookkeeping from making an in-flight provider command stale merely because another consumer joined or left a still-desired stream.

## Boundary

This slice changes the existing LiveFeed registry only. It does not create a second subscription registry, Provider Worker, LiveFeed runtime, provider adapter, or AI Monitor bridge. It does not wire production bootstrap, alter provider routing/currentness semantics, grant Entry Permission, or touch broker/execution.

The controller ingress API and AI Monitor runtime bridge remain separate follow-up slices. Production promotion remains frozen.

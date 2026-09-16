"""Desired subscription registry -- authoritative intent state only.

Single writer owns mutation (enforced by an internal lock, not by trusting
callers). This registry never calls any provider SDK and never reconciles
against actual provider state. It also owns consumer/reference membership so
one consumer cannot remove a semantic stream still required by another.

`revision` tracks provider-facing desired/control-plane state. Consumer-only
membership changes that leave the provider-facing desired set unchanged do
not invalidate in-flight provider commands; those changes advance the
separate `ownership_revision` instead.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace

from data_provider.live_feed_types import BindingStrength, ControlPlaneState, SemanticStreamKey


LEGACY_DEFAULT_CONSUMER = "LEGACY_DEFAULT"


def _normalize_consumer_id(consumer_id: str) -> str:
    normalized = str(consumer_id).strip()
    if not normalized:
        raise ValueError("consumer_id is required")
    return normalized


@dataclass(frozen=True)
class DesiredRegistryEntry:
    semantic_stream_key: SemanticStreamKey
    stream_subscription_epoch: int
    control_plane_state: ControlPlaneState
    binding_strength: BindingStrength
    consumer_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DesiredRegistrySnapshot:
    revision: int
    entries: tuple[DesiredRegistryEntry, ...]
    ownership_revision: int = 0


def _sort_key(entry: DesiredRegistryEntry) -> tuple:
    key = entry.semantic_stream_key
    return (
        key.provider_id,
        key.market,
        key.symbol,
        key.stream_type,
        key.timeframe or "",
        key.session_mode or "",
        key.adjustment_mode or "",
        key.feed or "",
    )


class DesiredSubscriptionRegistry:
    """Provider-neutral desired subscription registry. Single writer.

    Provider subscription lifetime is reference-counted by stable consumer ID:
    the first consumer creates provider-facing desired intent and the last
    consumer removal deletes it. Intermediate consumer add/remove operations
    change ownership evidence only.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._revision = 0
        self._ownership_revision = 0
        self._entries: dict[SemanticStreamKey, DesiredRegistryEntry] = {}
        self._last_epoch_by_key: dict[SemanticStreamKey, int] = {}

    def add_desired(self, key: SemanticStreamKey) -> DesiredRegistrySnapshot:
        """Compatibility API for the pre-consumer-aware caller surface."""
        return self.add_desired_for_consumer(key, LEGACY_DEFAULT_CONSUMER)

    def add_desired_for_consumer(
        self, key: SemanticStreamKey, consumer_id: str
    ) -> DesiredRegistrySnapshot:
        """Register one consumer's interest in `key`."""
        consumer = _normalize_consumer_id(consumer_id)
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                if consumer in existing.consumer_ids:
                    return self._snapshot_locked()
                consumers = tuple(sorted((*existing.consumer_ids, consumer)))
                self._entries[key] = replace(existing, consumer_ids=consumers)
                self._ownership_revision += 1
                return self._snapshot_locked()

            epoch = self._last_epoch_by_key.get(key, 1) or 1
            self._entries[key] = DesiredRegistryEntry(
                semantic_stream_key=key,
                stream_subscription_epoch=epoch,
                control_plane_state=ControlPlaneState.DESIRED,
                binding_strength=BindingStrength.UNVERIFIED,
                consumer_ids=(consumer,),
            )
            self._last_epoch_by_key[key] = epoch
            self._revision += 1
            self._ownership_revision += 1
            return self._snapshot_locked()

    def remove_desired(self, key: SemanticStreamKey) -> DesiredRegistrySnapshot:
        """Compatibility API: release only the legacy caller's reference."""
        return self.remove_desired_for_consumer(key, LEGACY_DEFAULT_CONSUMER)

    def remove_desired_for_consumer(
        self, key: SemanticStreamKey, consumer_id: str
    ) -> DesiredRegistrySnapshot:
        """Release one consumer's interest without harming other consumers."""
        consumer = _normalize_consumer_id(consumer_id)
        with self._lock:
            existing = self._entries.get(key)
            if existing is None or consumer not in existing.consumer_ids:
                return self._snapshot_locked()

            remaining = tuple(item for item in existing.consumer_ids if item != consumer)
            self._ownership_revision += 1
            if remaining:
                self._entries[key] = replace(existing, consumer_ids=remaining)
                return self._snapshot_locked()

            del self._entries[key]
            self._revision += 1
            return self._snapshot_locked()

    def readd_new_incarnation(self, key: SemanticStreamKey) -> DesiredRegistrySnapshot:
        """Re-add `key` as a NEW controller intent incarnation.

        This compatibility operation belongs to the legacy/default consumer.
        Existing consumer references are preserved so an incarnation reset
        cannot silently discard another consumer's ownership.
        """
        with self._lock:
            prior_epoch = self._last_epoch_by_key.get(key, 0)
            new_epoch = prior_epoch + 1
            existing = self._entries.get(key)
            existing_consumers = existing.consumer_ids if existing is not None else ()
            consumer_was_added = LEGACY_DEFAULT_CONSUMER not in existing_consumers
            consumers = tuple(sorted((*existing_consumers, LEGACY_DEFAULT_CONSUMER)))
            self._entries[key] = DesiredRegistryEntry(
                semantic_stream_key=key,
                stream_subscription_epoch=new_epoch,
                control_plane_state=ControlPlaneState.DESIRED,
                binding_strength=BindingStrength.UNVERIFIED,
                consumer_ids=consumers,
            )
            self._last_epoch_by_key[key] = new_epoch
            self._revision += 1
            if consumer_was_added:
                self._ownership_revision += 1
            return self._snapshot_locked()

    def set_control_plane_state(
        self, key: SemanticStreamKey, state: ControlPlaneState, *, binding_strength: BindingStrength | None = None
    ) -> DesiredRegistrySnapshot:
        """Update observed control-plane state for an existing entry."""
        with self._lock:
            entry = self._entries[key]
            self._entries[key] = replace(
                entry,
                control_plane_state=state,
                binding_strength=binding_strength if binding_strength is not None else entry.binding_strength,
            )
            self._revision += 1
            return self._snapshot_locked()

    def snapshot(self) -> DesiredRegistrySnapshot:
        with self._lock:
            return self._snapshot_locked()

    def _snapshot_locked(self) -> DesiredRegistrySnapshot:
        entries = tuple(sorted(self._entries.values(), key=_sort_key))
        return DesiredRegistrySnapshot(
            revision=self._revision,
            entries=entries,
            ownership_revision=self._ownership_revision,
        )

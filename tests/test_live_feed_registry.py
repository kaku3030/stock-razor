import pytest

from data_provider.live_feed_types import BindingStrength, ControlPlaneState, SemanticStreamKey
from src.services.live_feed.registry import DesiredSubscriptionRegistry, LEGACY_DEFAULT_CONSUMER

KEY = SemanticStreamKey(provider_id="futu", market="HK", symbol="HK.00700", stream_type="QUOTE")


def test_revision_increments_on_add() -> None:
    registry = DesiredSubscriptionRegistry()
    assert registry.snapshot().revision == 0
    snap = registry.add_desired(KEY)
    assert snap.revision == 1
    assert snap.ownership_revision == 1
    assert len(snap.entries) == 1
    assert snap.entries[0].semantic_stream_key == KEY
    assert snap.entries[0].control_plane_state is ControlPlaneState.DESIRED
    assert snap.entries[0].binding_strength is BindingStrength.UNVERIFIED
    assert snap.entries[0].consumer_ids == (LEGACY_DEFAULT_CONSUMER,)


def test_revision_increments_on_remove() -> None:
    registry = DesiredSubscriptionRegistry()
    registry.add_desired(KEY)
    snap = registry.remove_desired(KEY)
    assert snap.revision == 2
    assert snap.ownership_revision == 2
    assert snap.entries == ()


def test_noop_mutation_does_not_bump_revision() -> None:
    registry = DesiredSubscriptionRegistry()
    snap = registry.remove_desired(KEY)
    assert snap.revision == 0
    assert snap.ownership_revision == 0

    registry.add_desired(KEY)
    after_add = registry.snapshot()
    snap2 = registry.add_desired(KEY)
    assert snap2.revision == after_add.revision
    assert snap2.ownership_revision == after_add.ownership_revision


def test_readd_new_incarnation_bumps_epoch_and_revision() -> None:
    registry = DesiredSubscriptionRegistry()
    snap1 = registry.add_desired(KEY)
    assert snap1.entries[0].stream_subscription_epoch == 1
    registry.remove_desired(KEY)
    snap3 = registry.readd_new_incarnation(KEY)
    assert snap3.entries[0].stream_subscription_epoch == 2
    assert snap3.revision == 3


def test_readd_new_incarnation_resets_binding_strength() -> None:
    registry = DesiredSubscriptionRegistry()
    registry.add_desired(KEY)
    registry.set_control_plane_state(KEY, ControlPlaneState.ACKED, binding_strength=BindingStrength.VERIFIED)
    snap = registry.readd_new_incarnation(KEY)
    assert snap.entries[0].binding_strength is BindingStrength.UNVERIFIED
    assert snap.entries[0].control_plane_state is ControlPlaneState.DESIRED


def test_snapshot_ordering_is_deterministic() -> None:
    registry = DesiredSubscriptionRegistry()
    key_b = SemanticStreamKey(provider_id="futu", market="HK", symbol="HK.09988", stream_type="QUOTE")
    key_a = SemanticStreamKey(provider_id="futu", market="HK", symbol="HK.00700", stream_type="K_1M")
    registry.add_desired(key_b)
    registry.add_desired(key_a)
    snap1 = registry.snapshot()
    registry2 = DesiredSubscriptionRegistry()
    registry2.add_desired(key_a)
    registry2.add_desired(key_b)
    snap2 = registry2.snapshot()
    assert [e.semantic_stream_key for e in snap1.entries] == [e.semantic_stream_key for e in snap2.entries]


def test_set_control_plane_state_requires_existing_entry() -> None:
    registry = DesiredSubscriptionRegistry()
    with pytest.raises(KeyError):
        registry.set_control_plane_state(KEY, ControlPlaneState.ACKED)


def test_snapshot_is_immutable_and_not_affected_by_further_mutation() -> None:
    registry = DesiredSubscriptionRegistry()
    registry.add_desired(KEY)
    snap = registry.snapshot()
    registry.remove_desired(KEY)
    assert len(snap.entries) == 1


def test_additional_consumer_does_not_bump_provider_revision() -> None:
    registry = DesiredSubscriptionRegistry()
    first = registry.add_desired_for_consumer(KEY, "AI_MONITOR")
    second = registry.add_desired_for_consumer(KEY, "PORTFOLIO")
    assert first.revision == 1
    assert second.revision == 1
    assert second.ownership_revision == 2
    assert second.entries[0].consumer_ids == ("AI_MONITOR", "PORTFOLIO")


def test_removing_one_consumer_keeps_shared_stream_desired() -> None:
    registry = DesiredSubscriptionRegistry()
    registry.add_desired_for_consumer(KEY, "AI_MONITOR")
    registry.add_desired_for_consumer(KEY, "PORTFOLIO")
    snap = registry.remove_desired_for_consumer(KEY, "AI_MONITOR")
    assert snap.revision == 1
    assert snap.ownership_revision == 3
    assert len(snap.entries) == 1
    assert snap.entries[0].consumer_ids == ("PORTFOLIO",)


def test_last_consumer_removal_drops_provider_desired_intent() -> None:
    registry = DesiredSubscriptionRegistry()
    registry.add_desired_for_consumer(KEY, "AI_MONITOR")
    registry.add_desired_for_consumer(KEY, "PORTFOLIO")
    registry.remove_desired_for_consumer(KEY, "AI_MONITOR")
    snap = registry.remove_desired_for_consumer(KEY, "PORTFOLIO")
    assert snap.revision == 2
    assert snap.ownership_revision == 4
    assert snap.entries == ()


def test_legacy_remove_cannot_remove_another_consumers_stream() -> None:
    registry = DesiredSubscriptionRegistry()
    registry.add_desired_for_consumer(KEY, "AI_MONITOR")
    snap = registry.remove_desired(KEY)
    assert snap.revision == 1
    assert snap.ownership_revision == 1
    assert snap.entries[0].consumer_ids == ("AI_MONITOR",)


def test_readd_preserves_other_consumers_and_adds_legacy_owner() -> None:
    registry = DesiredSubscriptionRegistry()
    registry.add_desired_for_consumer(KEY, "AI_MONITOR")
    snap = registry.readd_new_incarnation(KEY)
    assert snap.entries[0].stream_subscription_epoch == 2
    assert snap.entries[0].consumer_ids == ("AI_MONITOR", LEGACY_DEFAULT_CONSUMER)
    assert snap.revision == 2
    assert snap.ownership_revision == 2


def test_consumer_id_is_required() -> None:
    registry = DesiredSubscriptionRegistry()
    with pytest.raises(ValueError, match="consumer_id is required"):
        registry.add_desired_for_consumer(KEY, "  ")
    with pytest.raises(ValueError, match="consumer_id is required"):
        registry.remove_desired_for_consumer(KEY, "")

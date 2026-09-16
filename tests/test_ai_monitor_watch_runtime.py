from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from data_provider.live_feed_types import SemanticStreamKey
from src.services.ai_monitor.watch_runtime import (
    DurableUserPins,
    JsonUserPinStore,
    PersistedUserPin,
    SubscriptionReconciliationError,
    WatchRuntimeError,
    WatchStreamBinding,
    WatchStreamSpec,
    WatchUniverseLiveFeedBridge,
)
from src.services.ai_monitor.watch_universe import (
    ActiveWatchUniverse,
    RadarWatchContext,
    WatchIdentity,
)


NOW = datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)


class FakeController:
    def __init__(self, provider_id="alpaca") -> None:
        self.provider_id = provider_id
        self.add_calls = []
        self.remove_calls = []
        self.reject_add = False
        self.reject_remove = False

    def snapshot(self):
        return SimpleNamespace(provider_id=self.provider_id)

    def request_add_desired(self, key):
        self.add_calls.append(key)
        return SimpleNamespace(accepted=not self.reject_add, reason="QUEUE_FULL" if self.reject_add else None)

    def request_remove_desired(self, key):
        self.remove_calls.append(key)
        return SimpleNamespace(
            accepted=not self.reject_remove,
            reason="QUEUE_FULL" if self.reject_remove else None,
        )


class FailingStore:
    def load(self):
        return ()

    def replace(self, pins):
        raise WatchRuntimeError("disk unavailable")


def _bridge(controller=None):
    controller = controller or FakeController()
    return WatchUniverseLiveFeedBridge(
        {
            "us": WatchStreamBinding(
                controller=controller,
                spec=WatchStreamSpec(provider_id="alpaca", stream_type="BAR", timeframe="1m"),
            )
        }
    ), controller


def test_user_pin_is_durable_across_universe_restart(tmp_path) -> None:
    store = JsonUserPinStore(tmp_path / "user-pins.json")
    first = ActiveWatchUniverse()
    pins = DurableUserPins(store)

    persisted = pins.pin(first, market="us", symbol="qcom", activated_at=NOW)
    assert persisted.identity == WatchIdentity("us", "QCOM")
    assert first.get(persisted.identity).source_names == ("USER_PINNED",)

    restarted = ActiveWatchUniverse()
    restored = pins.restore(restarted)

    assert restored == (PersistedUserPin(WatchIdentity("us", "QCOM"), NOW),)
    assert restarted.get(WatchIdentity("us", "QCOM")).source_names == ("USER_PINNED",)


def test_unpin_persists_but_does_not_remove_radar_reason(tmp_path) -> None:
    store = JsonUserPinStore(tmp_path / "user-pins.json")
    universe = ActiveWatchUniverse()
    pins = DurableUserPins(store)
    identity = WatchIdentity("us", "ANET")
    universe.replace_radar(
        {identity: RadarWatchContext(candidate_id="anet-1", candidate_status="WATCH")},
        activated_at=NOW,
    )
    pins.pin(universe, market="us", symbol="ANET", activated_at=NOW)

    pins.unpin(universe, market="us", symbol="ANET")

    assert store.load() == ()
    assert universe.get(identity).source_names == ("RADAR",)


def test_persistence_failure_does_not_create_memory_only_pin() -> None:
    universe = ActiveWatchUniverse()
    pins = DurableUserPins(FailingStore())

    with pytest.raises(WatchRuntimeError, match="disk unavailable"):
        pins.pin(universe, market="us", symbol="VRT", activated_at=NOW)

    assert universe.snapshot(generated_at=NOW).active_identities == ()


def test_corrupt_pin_truth_fails_closed(tmp_path) -> None:
    path = tmp_path / "user-pins.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(WatchRuntimeError, match="cannot read"):
        JsonUserPinStore(path).load()


def test_bridge_adds_non_position_radar_candidate_to_existing_livefeed() -> None:
    bridge, controller = _bridge()
    universe = ActiveWatchUniverse()
    identity = WatchIdentity("us", "QCOM")
    universe.replace_radar(
        {identity: RadarWatchContext(candidate_id="qcom-1", candidate_status="WATCH")},
        activated_at=NOW,
    )

    delta = bridge.reconcile(universe.snapshot(generated_at=NOW))

    expected = SemanticStreamKey("alpaca", "US", "QCOM", "BAR", "1m")
    assert delta.added == (expected,)
    assert delta.removed == ()
    assert controller.add_calls == [expected]
    assert bridge.managed_keys == (expected,)


def test_bridge_removes_expired_watch_from_existing_livefeed() -> None:
    bridge, controller = _bridge()
    universe = ActiveWatchUniverse()
    universe.pin(market="us", symbol="VRT", activated_at=NOW)
    bridge.reconcile(universe.snapshot(generated_at=NOW))

    universe.unpin(market="us", symbol="VRT")
    delta = bridge.reconcile(universe.snapshot(generated_at=NOW))

    expected = SemanticStreamKey("alpaca", "US", "VRT", "BAR", "1m")
    assert delta.removed == (expected,)
    assert controller.remove_calls == [expected]
    assert bridge.managed_keys == ()


def test_bridge_is_idempotent_when_watch_set_does_not_change() -> None:
    bridge, controller = _bridge()
    universe = ActiveWatchUniverse()
    universe.pin(market="us", symbol="AMD", activated_at=NOW)
    snapshot = universe.snapshot(generated_at=NOW)

    bridge.reconcile(snapshot)
    delta = bridge.reconcile(snapshot)

    assert delta.changed is False
    assert len(controller.add_calls) == 1
    assert controller.remove_calls == []


def test_remove_enqueue_rejection_keeps_managed_key_for_retry() -> None:
    bridge, controller = _bridge()
    universe = ActiveWatchUniverse()
    universe.pin(market="us", symbol="VRT", activated_at=NOW)
    bridge.reconcile(universe.snapshot(generated_at=NOW))
    universe.unpin(market="us", symbol="VRT")
    controller.reject_remove = True

    with pytest.raises(SubscriptionReconciliationError, match="remove enqueue rejected"):
        bridge.reconcile(universe.snapshot(generated_at=NOW))

    assert len(bridge.managed_keys) == 1


def test_add_enqueue_rejection_does_not_claim_subscription_ownership() -> None:
    bridge, controller = _bridge()
    universe = ActiveWatchUniverse()
    universe.pin(market="us", symbol="AMD", activated_at=NOW)
    controller.reject_add = True

    with pytest.raises(SubscriptionReconciliationError, match="add enqueue rejected"):
        bridge.reconcile(universe.snapshot(generated_at=NOW))

    assert bridge.managed_keys == ()


def test_fresh_runtime_reset_readds_full_desired_universe() -> None:
    bridge, controller = _bridge()
    universe = ActiveWatchUniverse()
    universe.pin(market="us", symbol="AMD", activated_at=NOW)
    snapshot = universe.snapshot(generated_at=NOW)
    bridge.reconcile(snapshot)

    bridge.reset_after_runtime_restart()
    delta = bridge.reconcile(snapshot)

    assert len(delta.added) == 1
    assert len(controller.add_calls) == 2


def test_bridge_rejects_controller_provider_mismatch() -> None:
    controller = FakeController(provider_id="futu")

    with pytest.raises(ValueError, match="controller/provider mismatch"):
        WatchUniverseLiveFeedBridge(
            {
                "us": WatchStreamBinding(
                    controller=controller,
                    spec=WatchStreamSpec(provider_id="alpaca", stream_type="BAR"),
                )
            }
        )


def test_bridge_missing_market_binding_fails_closed() -> None:
    bridge, _ = _bridge()
    universe = ActiveWatchUniverse()
    universe.pin(market="cn", symbol="600519", activated_at=NOW)

    with pytest.raises(SubscriptionReconciliationError, match="no LiveFeed binding"):
        bridge.reconcile(universe.snapshot(generated_at=NOW))

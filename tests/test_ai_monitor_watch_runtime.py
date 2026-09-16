from datetime import datetime, timezone

import pytest

from src.services.ai_monitor.watch_runtime import (
    DurableUserPins,
    JsonUserPinStore,
    PersistedUserPin,
    WatchRuntimeError,
)
from src.services.ai_monitor.watch_universe import (
    ActiveWatchUniverse,
    RadarWatchContext,
    WatchIdentity,
)


NOW = datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)


class FailingStore:
    def load(self):
        return ()

    def replace(self, pins):
        raise WatchRuntimeError("disk unavailable")


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

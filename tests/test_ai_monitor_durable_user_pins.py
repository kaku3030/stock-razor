from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.repositories.ai_monitor_user_pin_repo import AIMonitorUserPinRepository
from src.services.ai_monitor.persistent_user_pins import PersistentUserPins
from src.services.ai_monitor.watch_universe import (
    ActiveWatchUniverse,
    RadarWatchContext,
    WatchIdentity,
    WatchSource,
)


NOW = datetime(2026, 9, 16, 2, 0, tzinfo=timezone.utc)


class TestDB:
    def __init__(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        self.Session = sessionmaker(bind=self.engine)

    def get_session(self):
        return self.Session()


@pytest.fixture
def repository():
    db = TestDB()
    repo = AIMonitorUserPinRepository(db)
    try:
        yield repo
    finally:
        db.engine.dispose()


def test_repository_persists_idempotent_pins_and_isolates_owners(repository) -> None:
    first = repository.pin(
        owner_id="user-a",
        market="US",
        symbol="nvda",
        pinned_at=NOW,
    )
    second = repository.pin(
        owner_id="user-a",
        market="us",
        symbol="NVDA",
        pinned_at=datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc),
    )
    repository.pin(
        owner_id="user-b",
        market="us",
        symbol="NVDA",
        pinned_at=NOW,
    )

    assert first == second
    assert first.market == "us"
    assert first.symbol == "NVDA"
    assert first.pinned_at == NOW
    assert [pin.symbol for pin in repository.list_pins(owner_id="user-a")] == ["NVDA"]
    assert [pin.symbol for pin in repository.list_pins(owner_id="user-b")] == ["NVDA"]


def test_pins_hydrate_into_a_fresh_universe_after_restart(repository) -> None:
    first_universe = ActiveWatchUniverse()
    first_service = PersistentUserPins(repository, first_universe, owner_id="user-a")
    first_service.pin(market="us", symbol="AAPL", pinned_at=NOW)

    restarted_universe = ActiveWatchUniverse()
    restarted_service = PersistentUserPins(repository, restarted_universe, owner_id="user-a")
    snapshot = restarted_service.hydrate(generated_at=NOW)

    item = snapshot.get(WatchIdentity("us", "AAPL"))
    assert item is not None
    assert item.sources == frozenset({WatchSource.USER_PINNED})
    assert item.activated_at == NOW


def test_hydrate_removes_only_stale_user_pin_reason(repository) -> None:
    universe = ActiveWatchUniverse()
    identity = WatchIdentity("us", "NVDA")
    universe.pin(market="us", symbol="NVDA", activated_at=NOW)
    universe.replace_radar(
        {identity: RadarWatchContext(candidate_status="WATCH")},
        activated_at=NOW,
    )
    service = PersistentUserPins(repository, universe, owner_id="user-a")

    snapshot = service.hydrate(generated_at=NOW)

    item = snapshot.get(identity)
    assert item is not None
    assert item.sources == frozenset({WatchSource.RADAR})


def test_unpin_is_durable_and_preserves_other_watch_sources(repository) -> None:
    universe = ActiveWatchUniverse()
    identity = WatchIdentity("us", "NVDA")
    service = PersistentUserPins(repository, universe, owner_id="user-a")
    service.pin(market="us", symbol="NVDA", pinned_at=NOW)
    universe.replace_radar(
        {identity: RadarWatchContext(candidate_status="WATCH")},
        activated_at=NOW,
    )

    snapshot = service.unpin(market="us", symbol="NVDA")

    item = snapshot.get(identity)
    assert item is not None
    assert item.sources == frozenset({WatchSource.RADAR})
    assert repository.list_pins(owner_id="user-a") == ()

    restarted = ActiveWatchUniverse()
    restarted_service = PersistentUserPins(repository, restarted, owner_id="user-a")
    restarted_snapshot = restarted_service.hydrate(generated_at=NOW)
    assert restarted_snapshot.get(identity) is None

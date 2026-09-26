"""Offline regression: a completed aggregate cannot launder stale 1m facts."""

from datetime import datetime, timedelta, timezone

from data_provider.market_data_adapter import Bar, SignalPermission, evaluate_health
from src.services.realtime_market_data import RealtimeMarketDataService


START = datetime(2026, 9, 17, 13, 30, tzinfo=timezone.utc)
HEALTH = evaluate_health(
    freshness=1, completeness=1, timestamp=1, provider=1,
    continuity=1, cross_check=1,
)


class ExistingOwnerAdapter:
    def get_session_status(self, market):
        assert market == "us"
        return "regular"

    def get_provider_health(self):
        return HEALTH


def _owner():
    service = RealtimeMarketDataService(
        ExistingOwnerAdapter(), freshness_limit_seconds=120,
    )
    for i in range(60):
        start = START + timedelta(minutes=i)
        service.ingest(Bar(
            symbol="NVDA", market="us", asset_type="stock", timeframe="1m",
            bar_start=start, bar_end=start + timedelta(minutes=1),
            open=200, high=201, low=199, close=200.5, volume=100,
            provider="alpaca", feed="iex", source_timestamp=start + timedelta(minutes=1),
            received_at=start + timedelta(minutes=1), session="regular",
            is_closed=True, is_complete=True, health=HEALTH,
        ))
    return service


def test_expired_final_minute_marks_completed_fifteen_and_sixty_minute_bars_stale():
    service = _owner()
    snapshot = service.snapshot("NVDA", as_of=START + timedelta(minutes=65))
    assert snapshot.minute_bars[-1].health.signal_permission is SignalPermission.WATCH_ONLY
    assert snapshot.bars_15m[-1].is_closed and snapshot.bars_15m[-1].is_complete
    assert snapshot.bars_1h[-1].is_closed and snapshot.bars_1h[-1].is_complete
    for derived in (snapshot.bars_15m[-1], snapshot.bars_1h[-1]):
        assert "STALE" in derived.quality_flags
        assert derived.health.signal_permission is not SignalPermission.NORMAL


def test_snapshot_read_does_not_mutate_owner_cache_or_permanently_poison_later_reads():
    service = _owner()
    original = service.minute_bars("NVDA")
    stale = service.snapshot("NVDA", as_of=START + timedelta(minutes=65))
    fresh = service.snapshot("NVDA", as_of=START + timedelta(minutes=60, seconds=30))
    assert "STALE" in stale.minute_bars[-1].quality_flags
    assert service.minute_bars("NVDA") == original
    assert "STALE" not in fresh.minute_bars[-1].quality_flags
    assert "STALE" not in fresh.bars_15m[-1].quality_flags
    assert "STALE" not in fresh.bars_1h[-1].quality_flags

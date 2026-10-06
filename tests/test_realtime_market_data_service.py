from datetime import datetime, timedelta, timezone

from data_provider.market_data_adapter import Bar, MarketDataAdapter, SignalPermission, evaluate_health
from src.services.realtime_market_data import RealtimeMarketDataService


START = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)  # US 09:30 EDT
GOOD = evaluate_health(freshness=1, completeness=1, timestamp=1, provider=1, continuity=1, cross_check=1)


def make_bar(index: int, *, close: float = 10, received_offset: int = 0) -> Bar:
    start = START + timedelta(minutes=index)
    return Bar(
        symbol="NVDA",
        market="us",
        asset_type="stock",
        timeframe="1m",
        bar_start=start,
        bar_end=start + timedelta(minutes=1),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=100,
        provider="alpaca",
        feed="iex",
        source_timestamp=start + timedelta(minutes=1),
        received_at=start + timedelta(minutes=1, seconds=received_offset),
        session="regular",
        is_closed=True,
        is_complete=True,
        health=GOOD,
    )


class FakeAdapter(MarketDataAdapter):
    def __init__(self, bars=None, session="regular"):
        self.bars = bars or []
        self.session = session
        self.callback = None

    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_bars(self, symbol, timeframe, start=None, end=None, limit=None):
        return self.bars

    def subscribe(self, symbols, timeframe="1m", callback=None):
        self.callback = callback

    def get_session_status(self, market):
        return self.session

    def get_provider_health(self):
        return GOOD

    def reconnect(self):
        return False


def test_seed_and_snapshot_build_multi_timeframes() -> None:
    source = [make_bar(index, close=10 + index / 10) for index in range(60)]
    service = RealtimeMarketDataService(FakeAdapter(source), max_minutes=120)

    assert service.seed("NVDA") == 60
    snapshot = service.snapshot("NVDA", as_of=START + timedelta(minutes=60))

    assert len(snapshot.minute_bars) == 60
    assert len(snapshot.bars_5m) == 12
    assert len(snapshot.bars_15m) == 4
    assert len(snapshot.bars_1h) == 1
    assert snapshot.provider == "alpaca"
    assert snapshot.feed == "iex"


def test_updated_minute_replaces_earlier_fact() -> None:
    service = RealtimeMarketDataService(FakeAdapter(), max_minutes=60)
    original = make_bar(0, close=10)
    corrected = make_bar(0, close=12, received_offset=30)

    assert service.ingest(original) is True
    assert service.ingest(corrected) is True
    assert service.minute_bars("NVDA")[0].close == 12


def test_older_duplicate_cannot_overwrite_correction() -> None:
    service = RealtimeMarketDataService(FakeAdapter(), max_minutes=60)
    corrected = make_bar(0, close=12, received_offset=30)
    original = make_bar(0, close=10)

    service.ingest(corrected)
    assert service.ingest(original) is False
    assert service.minute_bars("NVDA")[0].close == 12


def test_cache_retention_is_bounded_per_symbol() -> None:
    service = RealtimeMarketDataService(FakeAdapter(), max_minutes=60)
    for index in range(65):
        service.ingest(make_bar(index))

    cached = service.minute_bars("NVDA")
    assert len(cached) == 60
    assert cached[0].bar_start == START + timedelta(minutes=5)


def test_active_session_stale_snapshot_is_watch_only() -> None:
    service = RealtimeMarketDataService(FakeAdapter(session="regular"), max_minutes=60, freshness_limit_seconds=120)
    service.ingest(make_bar(0))

    snapshot = service.snapshot("NVDA", as_of=START + timedelta(minutes=5))

    assert snapshot.health.signal_permission is SignalPermission.WATCH_ONLY
    assert "STALE" in snapshot.minute_bars[-1].quality_flags


def test_staleness_never_upgrades_blocked_data() -> None:
    blocked = evaluate_health(
        freshness=1,
        completeness=1,
        timestamp=1,
        provider=1,
        continuity=1,
        cross_check=1,
        quality_flags=["invalid_ohlc"],
    )
    service = RealtimeMarketDataService(FakeAdapter(session="regular"), max_minutes=60)
    service.ingest(Bar(**{**make_bar(0).__dict__, "health": blocked, "quality_flags": blocked.quality_flags}))

    snapshot = service.snapshot("NVDA", as_of=START + timedelta(minutes=5))

    assert snapshot.health.signal_permission is SignalPermission.BLOCKED


def test_subscription_ingests_before_notifying_observer() -> None:
    adapter = FakeAdapter()
    service = RealtimeMarketDataService(adapter, max_minutes=60)
    observed = []
    service.subscribe(["NVDA"], observer=lambda bar: observed.append((bar, len(service.minute_bars("NVDA")))))

    adapter.callback(make_bar(0))

    assert observed[0][1] == 1


def test_service_rejects_preaggregated_or_indicator_input() -> None:
    service = RealtimeMarketDataService(FakeAdapter(), max_minutes=60)
    invalid = Bar(**{**make_bar(0).__dict__, "timeframe": "15m"})

    try:
        service.ingest(invalid)
    except ValueError as exc:
        assert "1m" in str(exc)
    else:
        raise AssertionError("service must accept facts at one-minute granularity only")

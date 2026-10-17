from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from data_provider.market_data_adapter import (
    Bar,
    MarketDataAdapter,
    evaluate_health,
)
from src.services.realtime_market_data import RealtimeMarketDataService


START = datetime(2026, 9, 1, 13, 30, tzinfo=timezone.utc)
GOOD = evaluate_health(
    freshness=1,
    completeness=1,
    timestamp=1,
    provider=1,
    continuity=1,
    cross_check=1,
)


class Adapter(MarketDataAdapter):
    def get_latest_quote(self, symbol):
        raise NotImplementedError

    def get_bars(self, symbol, timeframe, start=None, end=None, limit=None):
        return []

    def subscribe(self, symbols, timeframe="1m", callback=None):
        pass

    def get_session_status(self, market):
        return "regular"

    def get_provider_health(self):
        return GOOD

    def reconnect(self):
        return False


def bar(index: int, *, close: float = 10.0, received_offset: int = 0) -> Bar:
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
        provider="futu",
        feed="opend",
        source_timestamp=start + timedelta(minutes=1),
        received_at=start + timedelta(minutes=1, seconds=received_offset),
        session="regular",
        is_closed=True,
        is_complete=True,
        health=GOOD,
    )


def test_concurrent_distinct_minute_ingest_is_lossless_and_sorted():
    service = RealtimeMarketDataService(Adapter(), max_minutes=120)
    gate = Barrier(8)

    def worker(indices):
        gate.wait()
        for index in indices:
            service.ingest(bar(index, close=100 + index))

    groups = [list(range(offset, 80, 8)) for offset in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, group) for group in groups]
        for future in futures:
            future.result()

    cached = service.minute_bars("NVDA")
    assert len(cached) == 80
    assert [item.bar_start for item in cached] == [
        START + timedelta(minutes=index) for index in range(80)
    ]
    assert [item.close for item in cached] == [
        100 + index for index in range(80)
    ]


def test_concurrent_same_minute_corrections_preserve_latest_received_fact():
    service = RealtimeMarketDataService(Adapter(), max_minutes=60)
    gate = Barrier(16)

    candidates = [
        bar(0, close=100 + offset, received_offset=offset)
        for offset in range(16)
    ]

    def worker(candidate):
        gate.wait()
        return service.ingest(candidate)

    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(worker, candidate) for candidate in candidates]
        results = [future.result() for future in futures]

    cached = service.minute_bars("NVDA")
    assert len(cached) == 1
    assert cached[0].received_at == max(item.received_at for item in candidates)
    assert cached[0].close == 115
    assert any(results)


def test_concurrent_ingest_retention_bound_remains_exact():
    service = RealtimeMarketDataService(Adapter(), max_minutes=60)
    gate = Barrier(4)

    def worker(indices):
        gate.wait()
        for index in indices:
            service.ingest(bar(index))

    groups = [list(range(offset, 120, 4)) for offset in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker, group) for group in groups]
        for future in futures:
            future.result()

    cached = service.minute_bars("NVDA")
    assert len(cached) == 60
    assert cached[0].bar_start == START + timedelta(minutes=60)
    assert cached[-1].bar_start == START + timedelta(minutes=119)

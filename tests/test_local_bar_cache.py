from datetime import datetime, timedelta, timezone

import pytest

from data_provider.local_bar_cache import SettledBarCache


NOW = datetime(2026, 10, 7, 5, 0, tzinfo=timezone.utc)


def _bar(*, minutes_ago: int, close: float, settled: bool = True) -> dict:
    end = NOW - timedelta(minutes=minutes_ago)
    start = end - timedelta(minutes=1)
    return {
        "symbol": "US.AMD",
        "market": "us",
        "asset_type": "stock",
        "timeframe": "1m",
        "bar_start_utc": start.isoformat(),
        "bar_end_utc": end.isoformat(),
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 100,
        "amount": 1000,
        "provider": "futu",
        "feed": "opend",
        "is_closed": settled,
        "is_complete": settled,
        "quality_flags": [],
    }


def test_cache_accepts_only_closure_proven_bars(tmp_path):
    cache = SettledBarCache(tmp_path / "bars.sqlite3")

    result = cache.upsert_bars([
        _bar(minutes_ago=2, close=648.0),
        _bar(minutes_ago=1, close=649.0, settled=False),
    ])

    assert result["accepted"] == 1
    assert len(result["rejected"]) == 1
    assert result["canonical_authority"] is False
    assert result["live_trade"] is False
    rows = cache.read_bars(market="us", symbol="US.AMD", timeframe="1m")
    assert [row["close"] for row in rows] == [648.0]


def test_cache_upsert_is_idempotent_and_latest_value_wins(tmp_path):
    cache = SettledBarCache(tmp_path / "bars.sqlite3")
    first = _bar(minutes_ago=1, close=649.0)
    changed = {**first, "close": 650.0}

    cache.upsert_bars([first])
    cache.upsert_bars([changed])

    rows = cache.read_bars(market="us", symbol="US.AMD", timeframe="1m")
    assert len(rows) == 1
    assert rows[0]["close"] == 650.0
    assert cache.stats()["bar_count"] == 1


def test_cache_reads_bounded_oldest_to_newest_and_supports_paging(tmp_path):
    cache = SettledBarCache(tmp_path / "bars.sqlite3")
    bars = [
        _bar(minutes_ago=3, close=647.0),
        _bar(minutes_ago=2, close=648.0),
        _bar(minutes_ago=1, close=649.0),
    ]
    cache.upsert_bars(bars)

    latest = cache.read_bars(
        market="us",
        symbol="US.AMD",
        timeframe="1m",
        limit=2,
    )
    assert [row["close"] for row in latest] == [648.0, 649.0]

    older = cache.read_bars(
        market="us",
        symbol="US.AMD",
        timeframe="1m",
        limit=10,
        before_bar_end_utc=latest[0]["bar_end_utc"],
    )
    assert [row["close"] for row in older] == [647.0]


def test_cache_reports_real_compression_accounting(tmp_path):
    cache = SettledBarCache(tmp_path / "bars.sqlite3")
    cache.upsert_bars([
        _bar(minutes_ago=index + 1, close=650.0 + index)
        for index in range(20)
    ])

    stats = cache.stats()

    assert stats["bar_count"] == 20
    assert stats["raw_bytes"] > 0
    assert stats["compressed_bytes"] > 0
    assert stats["compression_ratio"] is not None
    assert stats["canonical_authority"] is False


def test_cache_rejects_naive_timestamps_and_bad_limits(tmp_path):
    cache = SettledBarCache(tmp_path / "bars.sqlite3")
    bad = _bar(minutes_ago=1, close=649.0)
    bad["bar_end_utc"] = "2026-10-07T05:00:00"

    result = cache.upsert_bars([bad])
    assert result["accepted"] == 0
    assert "timezone-aware" in result["rejected"][0]["error"]

    with pytest.raises(ValueError):
        cache.read_bars(market="us", symbol="US.AMD", timeframe="1m", limit=0)

from datetime import datetime, timedelta, timezone

from src.services.vti_market_data import VtiMarketDataService


NOW = datetime(2026, 10, 7, 13, 0, tzinfo=timezone.utc)


def _bar(index: int, *, settled: bool = True) -> dict:
    end = NOW + timedelta(minutes=index)
    start = end - timedelta(minutes=1)
    return {
        "symbol": "US.AMD",
        "market": "us",
        "asset_type": "stock",
        "timeframe": "1m",
        "bar_start_utc": start.isoformat(),
        "bar_end_utc": end.isoformat(),
        "open": 100 + index,
        "high": 101 + index,
        "low": 99 + index,
        "close": 100.5 + index,
        "volume": 1000 + index,
        "amount": 100000 + index,
        "provider": "futu",
        "feed": "opend",
        "is_closed": settled,
        "is_complete": settled,
        "quality_flags": [],
    }


def _reader_with(bars: list[dict], *, status: str = "PASS"):
    def _reader(symbol, timeframe="15m", limit=100):
        return {
            "ok": bool(bars),
            "status": status,
            "symbol": "US.AMD",
            "timeframe": timeframe,
            "bars": bars[-limit:],
            "bar_count": min(len(bars), limit),
            "total_bar_count": len(bars),
            "source_age_seconds": 5,
            "repo_sha": "a" * 40,
            "runtime_instance_id": "runtime-1",
            "sequence": 10,
            "emitted_at_utc": NOW.isoformat(),
            "delivery_mode": "REALTIME",
            "bar_closure": "PROVEN",
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }

    return _reader


def test_initial_read_writes_only_settled_canonical_bars(tmp_path):
    bars = [_bar(1), _bar(2), _bar(3, settled=False)]
    service = VtiMarketDataService(
        cache_enabled=True,
        cache_path=tmp_path / "bars.sqlite3",
        us_reader=_reader_with(bars),
    )

    result = service.read_us_bars("AMD", timeframe="1m", limit=10)

    assert result["ok"] is True
    assert result["status"] == "PASS"
    assert [bar["close"] for bar in result["bars"]] == [101.5, 102.5]
    assert result["cache_write"]["accepted"] == 2
    assert result["cache_write"]["rejected"] == []
    assert result["canonical_authority"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_cache_supports_evidence_backed_left_pagination(tmp_path):
    bars = [_bar(index) for index in range(1, 7)]
    service = VtiMarketDataService(
        cache_enabled=True,
        cache_path=tmp_path / "bars.sqlite3",
        us_reader=_reader_with(bars),
    )

    # Warm the downstream cache from an explicitly requested canonical window.
    # Historical pagination must never trigger an implicit upstream backfill.
    service.read_us_bars("AMD", timeframe="1m", limit=10)
    latest = service.read_us_bars("AMD", timeframe="1m", limit=3)
    assert len(latest["bars"]) == 3

    before = latest["bars"][0]["bar_end_utc"]
    older = service.read_us_bars(
        "AMD",
        timeframe="1m",
        limit=2,
        before=before,
    )

    assert older["source"] == "settled_cache"
    assert [bar["close"] for bar in older["bars"]] == [102.5, 103.5]
    assert older["has_more_before"] is True


def test_cache_only_fallback_is_explicit_when_canonical_has_no_bars(tmp_path):
    path = tmp_path / "bars.sqlite3"
    warm = VtiMarketDataService(
        cache_enabled=True,
        cache_path=path,
        us_reader=_reader_with([_bar(1), _bar(2)]),
    )
    warm.read_us_bars("AMD", timeframe="1m", limit=10)

    offline = VtiMarketDataService(
        cache_enabled=True,
        cache_path=path,
        us_reader=_reader_with([], status="UNAVAILABLE"),
    )
    result = offline.read_us_bars("AMD", timeframe="1m", limit=10)

    assert result["ok"] is True
    assert result["status"] == "CACHE_ONLY"
    assert result["source"] == "settled_cache"
    assert result["source_status"] == "UNAVAILABLE"
    assert len(result["bars"]) == 2


def test_cache_disabled_preserves_canonical_read_without_filesystem_side_effect(tmp_path):
    cache_path = tmp_path / "disabled.sqlite3"
    service = VtiMarketDataService(
        cache_enabled=False,
        cache_path=cache_path,
        us_reader=_reader_with([_bar(1)]),
    )

    result = service.read_us_bars("AMD", timeframe="1m", limit=10)

    assert result["ok"] is True
    assert result["cache_status"] == "DISABLED"
    assert not cache_path.exists()


def test_before_is_cache_only_and_does_not_call_canonical_reader(tmp_path):
    calls = 0

    def reader(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _reader_with([_bar(1)])(*args, **kwargs)

    service = VtiMarketDataService(
        cache_enabled=True,
        cache_path=tmp_path / "bars.sqlite3",
        us_reader=reader,
    )
    service.read_us_bars("AMD", timeframe="1m", limit=10)
    assert calls == 1

    service.read_us_bars(
        "AMD",
        timeframe="1m",
        limit=10,
        before=_bar(1)["bar_end_utc"],
    )
    assert calls == 1


def test_invalid_timeframe_limit_and_naive_before_fail_closed(tmp_path):
    service = VtiMarketDataService(
        cache_enabled=False,
        cache_path=tmp_path / "bars.sqlite3",
        us_reader=_reader_with([_bar(1)]),
    )

    for kwargs in (
        {"timeframe": "tick"},
        {"limit": 0},
        {"before": "2026-10-07T13:00:00"},
    ):
        try:
            service.read_us_bars("AMD", **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {kwargs}")

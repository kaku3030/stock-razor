from datetime import datetime, timezone

import pytest

from src.services.live_feed.futu_k1m_forming_accumulator import FutuK1MFormingAccumulator
from src.services.live_feed.futu_research_bridge import closed_futu_minute_to_bar


def _closed_minute(time_key="2026-10-05 10:52:00"):
    accumulator = FutuK1MFormingAccumulator()
    accumulator.ingest({
        "code": "US.AMD",
        "time_key": time_key,
        "open": 100,
        "high": 101,
        "low": 99,
        "close": 100.5,
        "volume": 10,
        "turnover": 1000,
    })
    closed, _ = accumulator.ingest({
        "code": "US.AMD",
        "time_key": (
            "2026-10-05 10:53:00"
            if time_key.startswith("2026-10-05")
            else "2026-01-05 10:53:00"
        ),
        "open": 100.5,
        "high": 102,
        "low": 100,
        "close": 101,
        "volume": 5,
        "turnover": 500,
    })
    return closed


def test_bridge_rejects_forming_minute():
    accumulator = FutuK1MFormingAccumulator()
    _, forming = accumulator.ingest({
        "code": "US.AMD",
        "time_key": "2026-10-05 10:52:00",
        "open": 100,
        "high": 101,
        "low": 99,
        "close": 100.5,
        "volume": 10,
        "turnover": 1000,
    })
    with pytest.raises(ValueError, match="forming"):
        closed_futu_minute_to_bar(
            forming,
            received_at=datetime(2026, 10, 5, 14, 52, 2, tzinfo=timezone.utc),
        )


def test_fresh_closed_bar_promotes_timestamp_health_without_laundering_other_gates():
    bar = closed_futu_minute_to_bar(
        _closed_minute(),
        received_at=datetime(2026, 10, 5, 14, 52, 2, tzinfo=timezone.utc),
    )

    assert bar.is_closed and bar.is_complete
    assert bar.close == 100.5 and bar.volume == 10
    assert bar.bar_start == datetime(2026, 10, 5, 14, 51, tzinfo=timezone.utc)
    assert bar.bar_end == datetime(2026, 10, 5, 14, 52, tzinfo=timezone.utc)
    assert bar.source_timestamp == bar.bar_end
    assert bar.received_at == datetime(2026, 10, 5, 14, 52, 2, tzinfo=timezone.utc)
    assert "TIMESTAMP_MISMATCH" not in bar.quality_flags
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" not in bar.quality_flags
    assert "STALE" not in bar.quality_flags
    assert bar.latency_ms == 2000
    assert bar.freshness_ms == 2000
    assert bar.health.score == 90
    assert bar.health.signal_permission.value == "normal"


def test_stale_closed_bar_fails_closed_without_revoking_proven_timestamp_semantics():
    bar = closed_futu_minute_to_bar(
        _closed_minute(),
        received_at=datetime(2026, 10, 5, 14, 54, 1, tzinfo=timezone.utc),
    )

    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" not in bar.quality_flags
    assert "TIMESTAMP_MISMATCH" not in bar.quality_flags
    assert "STALE" in bar.quality_flags
    assert bar.health.score == 65
    assert bar.health.signal_permission.value == "record_only"


def test_future_received_time_beyond_clock_skew_is_severely_blocked():
    bar = closed_futu_minute_to_bar(
        _closed_minute(),
        received_at=datetime(2026, 10, 5, 14, 51, 54, tzinfo=timezone.utc),
    )

    assert "TIMESTAMP_MISMATCH" in bar.quality_flags
    assert bar.health.score == 49
    assert bar.health.signal_permission.value == "blocked"


def test_freshness_boundary_at_120_seconds_remains_eligible():
    bar = closed_futu_minute_to_bar(
        _closed_minute(),
        received_at=datetime(2026, 10, 5, 14, 54, 0, tzinfo=timezone.utc),
    )

    assert "STALE" not in bar.quality_flags
    assert bar.health.score == 90
    assert bar.health.signal_permission.value == "normal"


def test_bridge_uses_dst_aware_us_eastern_binding_in_winter():
    bar = closed_futu_minute_to_bar(
        _closed_minute("2026-01-05 10:52:00"),
        received_at=datetime(2026, 1, 5, 15, 52, 1, tzinfo=timezone.utc),
    )

    assert bar.bar_start == datetime(2026, 1, 5, 15, 51, tzinfo=timezone.utc)
    assert bar.bar_end == datetime(2026, 1, 5, 15, 52, tzinfo=timezone.utc)
    assert bar.health.signal_permission.value == "normal"


def test_bridge_requires_timezone_aware_received_at():
    with pytest.raises(ValueError, match="timezone-aware"):
        closed_futu_minute_to_bar(
            _closed_minute(),
            received_at=datetime(2026, 10, 5, 14, 52, 2),
        )

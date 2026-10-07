from datetime import datetime, timezone

import pytest

from data_provider.market_data_adapter import SignalPermission
from src.services.live_feed.futu_k1m_warm_start import historical_futu_k1m_to_bar


ROW = {
    "code": "US.NVDA",
    "time_key": "2026-10-06 16:00:00",
    "open": 190.0,
    "high": 191.0,
    "low": 189.5,
    "close": 190.5,
    "volume": 12345,
    "turnover": 2345678.0,
}


def test_historical_k1m_uses_proven_interval_end_semantics() -> None:
    bar = historical_futu_k1m_to_bar(
        ROW,
        received_at=datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc),
    )

    assert bar.bar_end == datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
    assert bar.bar_start == datetime(2026, 10, 6, 19, 59, tzinfo=timezone.utc)
    assert bar.source_timestamp == bar.bar_end
    assert bar.is_closed is True
    assert bar.is_complete is True


def test_historical_k1m_is_explicitly_non_realtime() -> None:
    bar = historical_futu_k1m_to_bar(
        ROW,
        received_at=datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc),
    )

    assert "HISTORICAL_QUERY" in bar.quality_flags
    assert "STALE" in bar.quality_flags
    assert bar.health.signal_permission is SignalPermission.RECORD_ONLY
    assert bar.health.score <= 69


def test_historical_k1m_rejects_naive_receive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        historical_futu_k1m_to_bar(
            ROW,
            received_at=datetime(2026, 10, 7, 12, 0),
        )

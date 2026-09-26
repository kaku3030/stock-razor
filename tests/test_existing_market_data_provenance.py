"""Offline provenance regressions for the existing read-only CN quote bridge."""

from datetime import datetime, timezone
from types import SimpleNamespace

from data_provider.existing_market_data_adapter import ExistingMarketDataAdapter
from data_provider.market_data_adapter import SignalPermission


NOW = datetime(2026, 9, 17, 1, 30, 3, tzinfo=timezone.utc)


class FakeManager:
    def __init__(self, *, source_time, received_time):
        self._source_time = source_time
        self._received_time = received_time

    def get_realtime_quote(self, symbol, *, log_final_failure=True):
        assert log_final_failure is False
        return SimpleNamespace(
            price=10.5,
            market="cn",
            source="fake-cn-provider",
            provider_timestamp=self._source_time,
            fetched_at=self._received_time,
            is_stale=False,
            missing_fields=[],
            fallback_from=None,
        )


def quote(*, source_time, received_time):
    manager = FakeManager(source_time=source_time, received_time=received_time)
    return ExistingMarketDataAdapter(manager, now=lambda: NOW).get_latest_quote("600519")


def test_naive_china_source_clock_is_not_silently_treated_as_utc():
    result = quote(
        source_time="2026-09-17 09:30:00",
        received_time="2026-09-17T01:30:02Z",
    )
    assert result.source_timestamp == datetime(2026, 9, 17, 1, 30, 2, tzinfo=timezone.utc)
    assert "MISSING_SOURCE_TIMESTAMP" in result.quality_flags
    assert result.health.signal_permission is not SignalPermission.NORMAL


def test_explicit_eight_hour_offset_is_converted_without_guessing():
    result = quote(
        source_time="2026-09-17T09:30:00+08:00",
        received_time="2026-09-17T01:30:02Z",
    )
    assert result.source_timestamp == datetime(2026, 9, 17, 1, 30, tzinfo=timezone.utc)
    assert result.received_at == datetime(2026, 9, 17, 1, 30, 2, tzinfo=timezone.utc)
    assert "MISSING_SOURCE_TIMESTAMP" not in result.quality_flags


def test_naive_receipt_clock_does_not_grant_freshness():
    result = quote(
        source_time="2026-09-17T09:30:00+08:00",
        received_time="2026-09-17 09:30:02",
    )
    assert result.received_at == NOW
    assert "RECEIPT_TIMESTAMP_UNVERIFIED" in result.quality_flags
    assert result.health.signal_permission is not SignalPermission.NORMAL

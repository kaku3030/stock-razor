from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from data_provider.existing_market_data_adapter import ExistingMarketDataAdapter
from data_provider.market_data_adapter import SignalPermission

pytestmark = pytest.mark.unit


def _fixed_now() -> datetime:
    return datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)


class _Manager:
    def __init__(self, *, quote=None, frame=None, provider="test-provider") -> None:
        self.quote = quote
        self.frame = frame
        self.provider = provider

    def get_realtime_quote(self, symbol, log_final_failure=False):
        return self.quote

    def get_daily_data(self, symbol, start_date=None, end_date=None, days=30):
        return self.frame, self.provider


def _quote(price):
    return SimpleNamespace(
        price=price,
        fetched_at=_fixed_now(),
        provider_timestamp="2026-09-09T09:59:59Z",
        missing_fields=(),
        is_stale=False,
        fallback_from=None,
        source="fixture",
        market="us",
        volume=100,
        amount=1000,
    )


@pytest.mark.parametrize("dirty_price", ["--", "N/A", "not-a-number", "inf", "-inf"])
def test_malformed_quote_price_becomes_blocked_quality_evidence_not_exception(dirty_price) -> None:
    adapter = ExistingMarketDataAdapter(_Manager(quote=_quote(dirty_price)), now=_fixed_now)

    quote = adapter.get_latest_quote("AAPL")

    assert quote.price == 0.0
    assert "INVALID_NUMERIC" in quote.quality_flags
    assert "NON_POSITIVE_PRICE" in quote.quality_flags
    assert quote.health is not None
    assert quote.health.signal_permission is SignalPermission.BLOCKED


@pytest.mark.parametrize("missing_price", [None, "", float("nan")])
def test_missing_quote_price_is_not_misreported_as_malformed_numeric(missing_price) -> None:
    adapter = ExistingMarketDataAdapter(_Manager(quote=_quote(missing_price)), now=_fixed_now)

    quote = adapter.get_latest_quote("AAPL")

    assert quote.price == 0.0
    assert "INVALID_NUMERIC" not in quote.quality_flags
    assert "NON_POSITIVE_PRICE" in quote.quality_flags
    assert quote.health is not None
    assert quote.health.signal_permission is SignalPermission.BLOCKED


@pytest.mark.parametrize("field", ["open", "high", "low", "close", "volume"])
def test_any_malformed_required_bar_numeric_becomes_partial_blocked_bar(field) -> None:
    row = {
        "date": "2026-09-08",
        "open": "100.0",
        "high": "101.0",
        "low": "99.0",
        "close": "100.0",
        "volume": "1000",
        "amount": "100000",
    }
    row[field] = "N/A"
    adapter = ExistingMarketDataAdapter(_Manager(frame=pd.DataFrame([row])), now=_fixed_now)

    bars = adapter.get_bars("AAPL", "1d")

    assert len(bars) == 1
    bar = bars[0]
    assert bar.is_complete is False
    assert "INVALID_NUMERIC" in bar.quality_flags
    assert "PARTIAL_BAR" in bar.quality_flags
    assert bar.health is not None
    assert bar.health.signal_permission is SignalPermission.BLOCKED


def test_malformed_optional_amount_is_none_and_blocked_instead_of_raising() -> None:
    frame = pd.DataFrame(
        [
            {
                "date": "2026-09-08",
                "open": "100.0",
                "high": "101.0",
                "low": "99.0",
                "close": "100.0",
                "volume": "1000",
                "amount": "--",
            }
        ]
    )
    adapter = ExistingMarketDataAdapter(_Manager(frame=frame), now=_fixed_now)

    bar = adapter.get_bars("AAPL", "1d")[0]

    assert bar.amount is None
    assert bar.is_complete is True
    assert "INVALID_NUMERIC" in bar.quality_flags
    assert bar.health is not None
    assert bar.health.signal_permission is SignalPermission.BLOCKED


def test_negative_volume_remains_explicit_severe_quality_evidence() -> None:
    frame = pd.DataFrame(
        [
            {
                "date": "2026-09-08",
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": -1,
            }
        ]
    )
    adapter = ExistingMarketDataAdapter(_Manager(frame=frame), now=_fixed_now)

    bar = adapter.get_bars("AAPL", "1d")[0]

    assert "NEGATIVE_VOLUME" in bar.quality_flags
    assert bar.health is not None
    assert bar.health.signal_permission is SignalPermission.BLOCKED


def test_valid_numeric_strings_are_normalized_without_invalid_numeric_flag() -> None:
    frame = pd.DataFrame(
        [
            {
                "date": "2026-09-08",
                "open": "100.0",
                "high": "102.0",
                "low": "99.0",
                "close": "101.0",
                "volume": "1000",
                "amount": "101000",
            }
        ]
    )
    adapter = ExistingMarketDataAdapter(_Manager(frame=frame), now=_fixed_now)

    bar = adapter.get_bars("AAPL", "daily")[0]

    assert (bar.open, bar.high, bar.low, bar.close, bar.volume, bar.amount) == (
        100.0,
        102.0,
        99.0,
        101.0,
        1000.0,
        101000.0,
    )
    assert "INVALID_NUMERIC" not in bar.quality_flags

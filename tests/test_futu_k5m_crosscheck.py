from datetime import datetime, timedelta, timezone

import pytest

from data_provider.market_bar_builder import aggregate_bars
from data_provider.market_data_adapter import Bar
from src.services.live_feed.futu_k1m_forming_accumulator import FormingMinuteBar
from src.services.live_feed.futu_research_bridge import closed_futu_minute_to_bar
from src.services.live_feed.futu_k5m_crosscheck import (
    compare_canonical_5m_to_futu_native,
)


START = datetime(2026, 10, 5, 13, 30, tzinfo=timezone.utc)


def canonical_5m(*, closed=True, complete=True) -> Bar:
    return Bar(
        symbol="US.AMD",
        market="us",
        asset_type="stock",
        timeframe="5m",
        bar_start=START,
        bar_end=START + timedelta(minutes=5),
        open=100.0,
        high=103.0,
        low=99.5,
        close=102.5,
        volume=500.0,
        amount=51000.0,
        provider="futu",
        feed="opend",
        source_timestamp=START + timedelta(minutes=5),
        received_at=START + timedelta(minutes=5, seconds=1),
        session="regular",
        is_closed=closed,
        is_complete=complete,
    )


def native_row(**changes):
    row = {
        "code": "US.AMD",
        "time_key": "2026-10-05 09:35:00",
        "open": 100.0,
        "high": 103.0,
        "low": 99.5,
        "close": 102.5,
        "volume": 500.0,
        "turnover": 51000.0,
    }
    row.update(changes)
    return row


def test_exact_values_remain_unknown_until_timestamp_semantics_are_verified():
    result = compare_canonical_5m_to_futu_native(
        canonical_5m(), native_row(), native_is_forming=False
    )

    assert result.status == "UNKNOWN"
    assert result.mismatches == ()
    assert result.unknowns == ("TIMESTAMP_SEMANTICS_UNVERIFIED",)
    assert result.radar_admission == "BLOCKED"
    assert result.purpose == "CROSS_CHECK_ONLY"
    assert result.live_trade is False
    assert result.can_promote is False


def test_fully_verified_exact_match_passes_cross_check_without_promoting_radar():
    result = compare_canonical_5m_to_futu_native(
        canonical_5m(),
        native_row(),
        timezone_semantics_verified=True,
        native_is_forming=False,
    )

    assert result.status == "PASS"
    assert result.mismatches == ()
    assert result.unknowns == ()
    assert result.radar_admission == "BLOCKED"
    assert result.can_promote is False


def test_any_price_volume_turnover_or_time_difference_fails_closed():
    result = compare_canonical_5m_to_futu_native(
        canonical_5m(),
        native_row(
            time_key="2026-10-05 09:40:00",
            high=103.1,
            volume=501,
            turnover=51001,
        ),
        timezone_semantics_verified=False,
        native_is_forming=False,
    )

    assert result.status == "FAIL"
    assert "TIME_KEY_MISMATCH" in result.mismatches
    assert "HIGH_MISMATCH" in result.mismatches
    assert "VOLUME_MISMATCH" in result.mismatches
    assert "TURNOVER_MISMATCH" in result.mismatches
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" in result.unknowns


def test_forming_semantics_are_fail_closed_or_unknown_when_not_observed():
    mismatch = compare_canonical_5m_to_futu_native(
        canonical_5m(),
        native_row(),
        timezone_semantics_verified=True,
        native_is_forming=True,
    )
    unknown = compare_canonical_5m_to_futu_native(
        canonical_5m(),
        native_row(),
        timezone_semantics_verified=True,
        native_is_forming=None,
    )

    assert mismatch.status == "FAIL"
    assert "FORMING_SEMANTICS_MISMATCH" in mismatch.mismatches
    assert unknown.status == "UNKNOWN"
    assert unknown.unknowns == ("NATIVE_FORMING_SEMANTICS_UNKNOWN",)


def test_incomplete_canonical_bar_cannot_pass():
    result = compare_canonical_5m_to_futu_native(
        canonical_5m(complete=False),
        native_row(),
        timezone_semantics_verified=True,
        native_is_forming=False,
    )

    assert result.status == "UNKNOWN"
    assert "CANONICAL_INCOMPLETE" in result.unknowns


def test_non_us_or_non_5m_canonical_input_is_rejected():
    bar = Bar(**{**canonical_5m().__dict__, "timeframe": "15m"})
    with pytest.raises(ValueError, match="US 5m"):
        compare_canonical_5m_to_futu_native(bar, native_row())


def test_end_labeled_k1m_chain_matches_end_labeled_native_k5m():
    closed = []
    for index in range(5):
        # 09:31 labels the 09:30-09:31 interval; 09:35 labels 09:34-09:35.
        label = datetime(2026, 10, 5, 9, 31 + index)
        minute = FormingMinuteBar(
            "US.AMD", label, 100 + index, 101 + index, 99 + index,
            100.5 + index, 10 + index, 1000 + index, True
        )
        closed.append(
            closed_futu_minute_to_bar(
                minute,
                received_at=datetime(2026, 10, 5, 13, 36, tzinfo=timezone.utc),
            )
        )

    derived = aggregate_bars(
        closed, "5m", as_of=datetime(2026, 10, 5, 13, 36, tzinfo=timezone.utc)
    )
    assert len(derived) == 1
    bar = derived[0]
    assert bar.bar_start == datetime(2026, 10, 5, 13, 30, tzinfo=timezone.utc)
    assert bar.bar_end == datetime(2026, 10, 5, 13, 35, tzinfo=timezone.utc)

    result = compare_canonical_5m_to_futu_native(
        bar,
        {
            "code": "US.AMD",
            "time_key": "2026-10-05 09:35:00",
            "open": 100,
            "high": 105,
            "low": 99,
            "close": 104.5,
            "volume": 60,
            "turnover": 5010,
        },
        timezone_semantics_verified=True,
        native_is_forming=False,
    )
    assert result.status == "PASS"
    assert result.mismatches == ()
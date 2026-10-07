from datetime import datetime, timedelta, timezone

import pytest

from src.services.live_feed.futu_k1m_history import (
    normalize_futu_k1m_history_rows,
)


RECEIVED = datetime(2026, 10, 7, 4, 30, tzinfo=timezone.utc)


def row(time_key: str, **changes):
    payload = {
        "code": "US.AMD",
        "time_key": time_key,
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 10.0,
        "turnover": 1000.0,
    }
    payload.update(changes)
    return payload


def test_history_normalizer_only_closes_rows_proven_by_later_time_key():
    result = normalize_futu_k1m_history_rows(
        [
            row("2026-10-06 09:31:00"),
            row("2026-10-06 09:32:00", close=100.7),
            row("2026-10-06 09:33:00", close=100.9),
        ],
        received_at=RECEIVED,
        expected_symbol="US.AMD",
    )

    assert result.rows_seen == 3
    assert len(result.bars) == 2
    assert result.unresolved_tail.time_key == "2026-10-06 09:33:00"
    assert result.closure_method == "NEXT_TIME_KEY_PROGRESS"
    assert result.research_only is True
    assert result.can_promote is False
    assert result.radar_admission == "BLOCKED"
    assert result.live_trade is False

    first = result.bars[0]
    assert first.bar_start == datetime(2026, 10, 6, 13, 30, tzinfo=timezone.utc)
    assert first.bar_end == datetime(2026, 10, 6, 13, 31, tzinfo=timezone.utc)
    assert first.source_timestamp == first.bar_end
    assert first.provider == "futu"
    assert first.feed == "opend"
    assert first.is_closed is True
    assert first.is_complete is True
    assert first.quality_flags == ("HISTORICAL_QUERY",)
    assert first.health.score == 65
    assert first.health.signal_permission.value == "record_only"


def test_wall_clock_age_never_closes_unresolved_tail():
    result = normalize_futu_k1m_history_rows(
        [row("2026-10-06 16:00:00")],
        received_at=datetime(2026, 10, 20, tzinfo=timezone.utc),
    )

    assert result.bars == ()
    assert result.unresolved_tail.time_key == "2026-10-06 16:00:00"


def test_next_session_progress_can_close_prior_session_final_minute():
    result = normalize_futu_k1m_history_rows(
        [
            row("2026-10-06 16:00:00"),
            row("2026-10-07 09:31:00"),
        ],
        received_at=RECEIVED,
    )

    assert len(result.bars) == 1
    assert result.bars[0].bar_end == datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
    assert result.unresolved_tail.time_key == "2026-10-07 09:31:00"


def test_full_390_row_session_still_leaves_1600_unresolved():
    rows = []
    start = datetime(2026, 10, 6, 9, 31)
    for index in range(390):
        stamp = start + timedelta(minutes=index)
        rows.append(row(stamp.strftime("%Y-%m-%d %H:%M:%S")))

    result = normalize_futu_k1m_history_rows(
        rows,
        received_at=RECEIVED,
        expected_symbol="US.AMD",
    )

    assert result.rows_seen == 390
    assert len(result.bars) == 389
    assert result.bars[-1].bar_end == datetime(2026, 10, 6, 19, 59, tzinfo=timezone.utc)
    assert result.unresolved_tail.time_key == "2026-10-06 16:00:00"
    assert result.can_promote is False
    assert result.radar_admission == "BLOCKED"


def test_next_session_first_label_can_close_all_390_prior_session_rows():
    rows = []
    start = datetime(2026, 10, 6, 9, 31)
    for index in range(390):
        stamp = start + timedelta(minutes=index)
        rows.append(row(stamp.strftime("%Y-%m-%d %H:%M:%S")))
    rows.append(row("2026-10-07 09:31:00"))

    result = normalize_futu_k1m_history_rows(
        rows,
        received_at=RECEIVED,
        expected_symbol="US.AMD",
    )

    assert len(result.bars) == 390
    assert result.bars[-1].bar_end == datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc)
    assert result.unresolved_tail.time_key == "2026-10-07 09:31:00"


def test_winter_time_key_uses_dst_aware_eastern_binding():
    result = normalize_futu_k1m_history_rows(
        [
            row("2026-01-05 09:31:00"),
            row("2026-01-05 09:32:00"),
        ],
        received_at=datetime(2026, 1, 6, tzinfo=timezone.utc),
    )

    assert result.bars[0].bar_start == datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
    assert result.bars[0].bar_end == datetime(2026, 1, 5, 14, 31, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "rows",
    [
        [row("2026-10-06 09:32:00"), row("2026-10-06 09:31:00")],
        [row("2026-10-06 09:31:00"), row("2026-10-06 09:31:00")],
    ],
)
def test_out_of_order_or_duplicate_history_is_rejected(rows):
    with pytest.raises(ValueError, match="strictly increasing"):
        normalize_futu_k1m_history_rows(rows, received_at=RECEIVED)


def test_cross_symbol_rows_are_rejected():
    with pytest.raises(ValueError, match="exactly one symbol"):
        normalize_futu_k1m_history_rows(
            [
                row("2026-10-06 09:31:00"),
                row("2026-10-06 09:32:00", code="US.NVDA"),
            ],
            received_at=RECEIVED,
        )


def test_expected_symbol_prevents_symbol_laundering():
    with pytest.raises(ValueError, match="expected_symbol"):
        normalize_futu_k1m_history_rows(
            [
                row("2026-10-06 09:31:00"),
                row("2026-10-06 09:32:00"),
            ],
            received_at=RECEIVED,
            expected_symbol="US.NVDA",
        )


def test_invalid_ohlc_remains_a_blocked_historical_fact():
    result = normalize_futu_k1m_history_rows(
        [
            row("2026-10-06 09:31:00", low=102.0, high=101.0),
            row("2026-10-06 09:32:00"),
        ],
        received_at=RECEIVED,
    )

    bar = result.bars[0]
    assert "HISTORICAL_QUERY" in bar.quality_flags
    assert "INVALID_OHLC" in bar.quality_flags
    assert bar.health.signal_permission.value == "blocked"
    assert bar.health.score <= 49


def test_negative_volume_remains_a_blocked_historical_fact():
    result = normalize_futu_k1m_history_rows(
        [
            row("2026-10-06 09:31:00", volume=-1),
            row("2026-10-06 09:32:00"),
        ],
        received_at=RECEIVED,
    )

    bar = result.bars[0]
    assert "NEGATIVE_VOLUME" in bar.quality_flags
    assert bar.health.signal_permission.value == "blocked"


@pytest.mark.parametrize(
    "bad_time",
    ["2026-10-06 09:30:00", "2026-10-06 16:01:00", "not-a-time"],
)
def test_unqualified_or_malformed_time_key_is_rejected(bad_time):
    with pytest.raises(ValueError):
        normalize_futu_k1m_history_rows(
            [row(bad_time)],
            received_at=RECEIVED,
        )


def test_future_historical_fact_beyond_clock_skew_is_blocked():
    result = normalize_futu_k1m_history_rows(
        [
            row("2026-10-06 09:31:00"),
            row("2026-10-06 09:32:00"),
        ],
        received_at=datetime(2026, 10, 6, 13, 30, 54, tzinfo=timezone.utc),
    )

    bar = result.bars[0]
    assert "TIMESTAMP_MISMATCH" in bar.quality_flags
    assert bar.health.signal_permission.value == "blocked"
    assert bar.health.score <= 49


def test_future_historical_fact_at_clock_skew_boundary_is_not_timestamp_mismatch():
    result = normalize_futu_k1m_history_rows(
        [
            row("2026-10-06 09:31:00"),
            row("2026-10-06 09:32:00"),
        ],
        received_at=datetime(2026, 10, 6, 13, 30, 55, tzinfo=timezone.utc),
    )

    bar = result.bars[0]
    assert "TIMESTAMP_MISMATCH" not in bar.quality_flags
    assert bar.health.signal_permission.value == "record_only"


def test_received_at_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        normalize_futu_k1m_history_rows(
            [row("2026-10-06 09:31:00")],
            received_at=datetime(2026, 10, 7, 4, 30),
        )


def test_empty_history_is_safe_and_non_promoting():
    result = normalize_futu_k1m_history_rows([], received_at=RECEIVED)

    assert result.rows_seen == 0
    assert result.bars == ()
    assert result.unresolved_tail is None
    assert result.radar_admission == "BLOCKED"
    assert result.live_trade is False
    assert result.can_promote is False

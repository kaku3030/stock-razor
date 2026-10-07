from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from src.services.a_share_intraday_currentness import (
    expected_regular_session_end_labels,
    qualify_same_session_currentness,
)
from src.services.a_share_intraday_semantics import TimestampSemantic


CN = ZoneInfo("Asia/Shanghai")


def _cn(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=CN)


def test_expected_15m_and_60m_boundaries_respect_lunch_break():
    day = datetime(2026, 10, 8).date()

    q15 = expected_regular_session_end_labels(day, interval_minutes=15)
    q60 = expected_regular_session_end_labels(day, interval_minutes=60)

    assert [x.strftime("%H:%M") for x in q15] == [
        "09:45", "10:00", "10:15", "10:30",
        "10:45", "11:00", "11:15", "11:30",
        "13:15", "13:30", "13:45", "14:00",
        "14:15", "14:30", "14:45", "15:00",
    ]
    assert [x.strftime("%H:%M") for x in q60] == [
        "10:30", "11:30", "14:00", "15:00",
    ]


def test_15m_exact_latest_completed_boundary_is_proven():
    result = qualify_same_session_currentness(
        "2026-10-08 10:15",
        interval_minutes=15,
        timestamp_semantic=TimestampSemantic.BAR_END,
        observed_at=_cn("2026-10-08 10:17"),
    )

    assert result.status == "PASS"
    assert result.currentness_proven is True
    assert result.expected_completed_boundary.endswith("10:15:00+08:00")
    assert result.radar_admission == "BLOCKED"
    assert result.live_trade is False


def test_lunch_break_uses_1130_as_latest_completed_boundary():
    result = qualify_same_session_currentness(
        "2026-10-08 11:30",
        interval_minutes=15,
        timestamp_semantic=TimestampSemantic.BAR_END,
        observed_at=_cn("2026-10-08 12:20"),
    )

    assert result.status == "PASS"
    assert result.currentness_proven is True
    assert result.expected_completed_boundary.endswith("11:30:00+08:00")


def test_60m_afternoon_boundary_is_proven():
    result = qualify_same_session_currentness(
        "2026-10-08 14:00",
        interval_minutes=60,
        timestamp_semantic=TimestampSemantic.BAR_END,
        observed_at=_cn("2026-10-08 14:08"),
    )

    assert result.status == "PASS"
    assert result.currentness_proven is True


def test_holiday_or_weekend_prior_session_never_becomes_current():
    result = qualify_same_session_currentness(
        "2026-09-30 15:00",
        interval_minutes=15,
        timestamp_semantic=TimestampSemantic.BAR_END,
        observed_at=_cn("2026-10-07 14:30"),
    )

    assert result.status == "BLOCKED"
    assert result.currentness_proven is False
    assert result.reasons == ("LATEST_LABEL_NOT_OBSERVATION_DATE",)


def test_premarket_prior_session_stays_blocked():
    result = qualify_same_session_currentness(
        "2026-10-08 15:00",
        interval_minutes=15,
        timestamp_semantic=TimestampSemantic.BAR_END,
        observed_at=_cn("2026-10-09 09:10"),
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("LATEST_LABEL_NOT_OBSERVATION_DATE",)


def test_before_first_60m_boundary_cannot_be_current():
    result = qualify_same_session_currentness(
        "2026-10-08 10:30",
        interval_minutes=60,
        timestamp_semantic=TimestampSemantic.BAR_END,
        observed_at=_cn("2026-10-08 10:20"),
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("NO_COMPLETED_INTRADAY_BOUNDARY",)


def test_missing_expected_boundary_is_blocked():
    result = qualify_same_session_currentness(
        "2026-10-08 10:00",
        interval_minutes=15,
        timestamp_semantic=TimestampSemantic.BAR_END,
        observed_at=_cn("2026-10-08 10:17"),
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("EXPECTED_COMPLETED_BOUNDARY_NOT_REACHED",)
    assert result.expected_completed_boundary.endswith("10:15:00+08:00")


def test_provider_ahead_of_clock_is_blocked():
    result = qualify_same_session_currentness(
        "2026-10-08 10:30",
        interval_minutes=15,
        timestamp_semantic=TimestampSemantic.BAR_END,
        observed_at=_cn("2026-10-08 10:17"),
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("PROVIDER_TIMESTAMP_AHEAD_OF_EXPECTED_BOUNDARY",)


def test_off_grid_same_day_label_is_blocked():
    result = qualify_same_session_currentness(
        "2026-10-08 10:14",
        interval_minutes=15,
        timestamp_semantic=TimestampSemantic.BAR_END,
        observed_at=_cn("2026-10-08 10:17"),
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("TIMESTAMP_OFF_ADMITTED_GRID",)


def test_unknown_semantics_cannot_prove_currentness():
    result = qualify_same_session_currentness(
        "2026-10-08 10:15",
        interval_minutes=15,
        timestamp_semantic=TimestampSemantic.UNKNOWN,
        observed_at=_cn("2026-10-08 10:17"),
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("TIMESTAMP_SEMANTIC_NOT_BAR_END",)


def test_observed_at_must_be_timezone_aware():
    with pytest.raises(ValueError):
        qualify_same_session_currentness(
            "2026-10-08 10:15",
            interval_minutes=15,
            timestamp_semantic=TimestampSemantic.BAR_END,
            observed_at=datetime(2026, 10, 8, 10, 17),
        )


def test_utc_observation_is_converted_to_shanghai_clock():
    result = qualify_same_session_currentness(
        "2026-10-08 10:15",
        interval_minutes=15,
        timestamp_semantic=TimestampSemantic.BAR_END,
        observed_at=datetime(2026, 10, 8, 2, 17, tzinfo=timezone.utc),
    )

    assert result.status == "PASS"
    assert result.observed_at_market_local.endswith("+08:00")

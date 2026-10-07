from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from src.services.a_share_intraday_currentness import (
    expected_latest_completed_boundary,
    qualify_cn_intraday_currentness,
)


CN = ZoneInfo("Asia/Shanghai")


class FakeCalendar:
    def __init__(self, sessions):
        self.sessions = tuple(sorted(sessions))

    def is_session(self, value):
        day = value.date() if hasattr(value, "date") and not isinstance(value, date) else value
        return day in self.sessions

    def date_to_session(self, value, direction="none"):
        day = value.date() if hasattr(value, "date") and not isinstance(value, date) else value
        if direction == "previous":
            candidates = [session for session in self.sessions if session <= day]
            if not candidates:
                raise ValueError("no prior session")
            return candidates[-1]
        if day not in self.sessions:
            raise ValueError("not a session")
        return day


SESSIONS = [
    date(2026, 9, 29),
    date(2026, 9, 30),
    date(2026, 10, 8),
    date(2026, 10, 9),
]
CAL = FakeCalendar(SESSIONS)


def utc(y, m, d, hh, mm, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=CN).astimezone(timezone.utc)


@pytest.mark.parametrize("interval", [15, 60])
def test_golden_week_non_trading_day_accepts_sep30_close(interval):
    result = qualify_cn_intraday_currentness(
        "2026-09-30 15:00",
        interval_minutes=interval,
        observed_at_utc=utc(2026, 10, 7, 19, 30),
        timestamp_semantic="BAR_END",
        timestamp_qualification_status="PASS",
        session_calendar=CAL,
    )

    assert result.status == "PASS"
    assert result.expected_label == "2026-09-30 15:00"
    assert result.reason == "LATEST_COMPLETED_BOUNDARY_MATCH"
    assert result.continuity_proven is False
    assert result.radar_admission == "BLOCKED"
    assert result.live_trade is False
    assert result.can_promote is False


@pytest.mark.parametrize(
    ("interval", "observed_local", "expected"),
    [
        (15, (2026, 10, 8, 9, 40, 0), "2026-09-30 15:00"),
        (15, (2026, 10, 8, 9, 45, 20), "2026-09-30 15:00"),
        (15, (2026, 10, 8, 9, 45, 31), "2026-10-08 09:45"),
        (15, (2026, 10, 8, 11, 50, 0), "2026-10-08 11:30"),
        (15, (2026, 10, 8, 13, 5, 0), "2026-10-08 11:30"),
        (15, (2026, 10, 8, 13, 15, 31), "2026-10-08 13:15"),
        (15, (2026, 10, 8, 15, 0, 31), "2026-10-08 15:00"),
        (60, (2026, 10, 8, 10, 20, 0), "2026-09-30 15:00"),
        (60, (2026, 10, 8, 10, 30, 31), "2026-10-08 10:30"),
        (60, (2026, 10, 8, 12, 0, 0), "2026-10-08 11:30"),
        (60, (2026, 10, 8, 14, 0, 31), "2026-10-08 14:00"),
        (60, (2026, 10, 8, 15, 0, 31), "2026-10-08 15:00"),
    ],
)
def test_expected_boundary_respects_split_session_and_grace(
    interval, observed_local, expected
):
    y, m, d, hh, mm, ss = observed_local
    result = expected_latest_completed_boundary(
        interval_minutes=interval,
        observed_at_utc=utc(y, m, d, hh, mm, ss),
        completion_grace_seconds=30,
        session_calendar=CAL,
    )

    assert result.strftime("%Y-%m-%d %H:%M") == expected


def test_stale_bar_fails_against_latest_completed_boundary():
    result = qualify_cn_intraday_currentness(
        "2026-10-08 10:00",
        interval_minutes=15,
        observed_at_utc=utc(2026, 10, 8, 10, 15, 45),
        timestamp_semantic="BAR_END",
        timestamp_qualification_status="PASS",
        session_calendar=CAL,
    )

    assert result.status == "FAIL"
    assert result.reason == "EXPECTED_COMPLETED_BOUNDARY_NOT_REACHED"
    assert result.expected_label == "2026-10-08 10:15"


def test_ahead_bar_fails_closed():
    result = qualify_cn_intraday_currentness(
        "2026-10-08 10:30",
        interval_minutes=15,
        observed_at_utc=utc(2026, 10, 8, 10, 15, 45),
        timestamp_semantic="BAR_END",
        timestamp_qualification_status="PASS",
        session_calendar=CAL,
    )

    assert result.status == "FAIL"
    assert result.reason == "PROVIDER_LABEL_AHEAD_OF_EXPECTED_BOUNDARY"


def test_unqualified_timestamp_semantics_remain_unknown():
    result = qualify_cn_intraday_currentness(
        "2026-10-08 10:15",
        interval_minutes=15,
        observed_at_utc=utc(2026, 10, 8, 10, 16),
        timestamp_semantic="UNKNOWN",
        timestamp_qualification_status="BLOCKED",
        session_calendar=CAL,
    )

    assert result.status == "UNKNOWN"
    assert result.reason == "TIMESTAMP_SEMANTICS_NOT_QUALIFIED"


def test_off_grid_label_fails():
    result = qualify_cn_intraday_currentness(
        "2026-10-08 10:17",
        interval_minutes=15,
        observed_at_utc=utc(2026, 10, 8, 10, 20),
        timestamp_semantic="BAR_END",
        timestamp_qualification_status="PASS",
        session_calendar=CAL,
    )

    assert result.status == "FAIL"
    assert result.reason == "PROVIDER_LABEL_OFF_ADMITTED_GRID"


def test_non_trading_provider_date_fails():
    result = qualify_cn_intraday_currentness(
        "2026-10-07 15:00",
        interval_minutes=60,
        observed_at_utc=utc(2026, 10, 7, 19, 0),
        timestamp_semantic="BAR_END",
        timestamp_qualification_status="PASS",
        session_calendar=CAL,
    )

    assert result.status == "FAIL"
    assert result.reason == "PROVIDER_LABEL_ON_NON_TRADING_DATE"


def test_calendar_failure_never_promotes_currentness():
    class BrokenCalendar:
        def is_session(self, _value):
            raise RuntimeError("calendar down")

    result = qualify_cn_intraday_currentness(
        "2026-10-08 10:15",
        interval_minutes=15,
        observed_at_utc=utc(2026, 10, 8, 10, 16),
        timestamp_semantic="BAR_END",
        timestamp_qualification_status="PASS",
        session_calendar=BrokenCalendar(),
    )

    assert result.status == "UNKNOWN"
    assert result.reason.startswith("CALENDAR_EVIDENCE_UNAVAILABLE:")
    assert result.can_promote is False


def test_real_xshg_calendar_knows_2026_golden_week():
    pytest.importorskip("exchange_calendars")

    result = qualify_cn_intraday_currentness(
        "2026-09-30 15:00",
        interval_minutes=15,
        observed_at_utc=utc(2026, 10, 7, 19, 0),
        timestamp_semantic="BAR_END",
        timestamp_qualification_status="PASS",
    )

    assert result.status == "PASS"
    assert result.expected_label == "2026-09-30 15:00"


def test_naive_observation_time_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        qualify_cn_intraday_currentness(
            "2026-10-08 10:15",
            interval_minutes=15,
            observed_at_utc=datetime(2026, 10, 8, 2, 16),
            timestamp_semantic="BAR_END",
            timestamp_qualification_status="PASS",
            session_calendar=CAL,
        )


def test_grace_must_be_bounded():
    with pytest.raises(ValueError, match="between 0 and 300"):
        expected_latest_completed_boundary(
            interval_minutes=15,
            observed_at_utc=utc(2026, 10, 8, 10, 0),
            completion_grace_seconds=301,
            session_calendar=CAL,
        )

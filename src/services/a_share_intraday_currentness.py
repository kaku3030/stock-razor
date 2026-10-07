"""Fail-closed A-share intraday Currentness qualification.

This module starts only after provider timestamp semantics are independently
qualified as BAR_END.  It uses the XSHG trading calendar only to identify the
relevant trading session, then compares the provider's latest 15m/60m label
with the latest *completed* canonical A-share boundary.

A PASS is Currentness evidence only.  It does not prove continuity, data
delivery mode, Radar admission, signal actionability, or execution safety.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo


CN = ZoneInfo("Asia/Shanghai")
SUPPORTED_INTERVALS = frozenset({15, 60})
END_BOUNDARIES = {
    15: (
        "09:45", "10:00", "10:15", "10:30",
        "10:45", "11:00", "11:15", "11:30",
        "13:15", "13:30", "13:45", "14:00",
        "14:15", "14:30", "14:45", "15:00",
    ),
    60: ("10:30", "11:30", "14:00", "15:00"),
}


class SessionCalendar(Protocol):
    def is_session(self, session: object) -> bool: ...
    def date_to_session(self, session: object, direction: str = "none") -> object: ...


@dataclass(frozen=True)
class CnIntradayCurrentnessResult:
    status: str
    reason: str
    interval_minutes: int
    provider_label: str | None
    expected_label: str | None
    observed_at_utc: datetime
    session_date: str | None
    calendar_id: str = "XSHG"
    timestamp_semantic: str = "BAR_END"
    timestamp_qualification_status: str = "PASS"
    continuity_proven: bool = False
    radar_admission: str = "BLOCKED"
    live_trade: bool = False

    @property
    def can_promote(self) -> bool:
        return False

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["observed_at_utc"] = self.observed_at_utc.isoformat()
        payload["can_promote"] = self.can_promote
        return payload


def _calendar() -> SessionCalendar:
    try:
        import exchange_calendars as xcals
    except ImportError as exc:
        raise RuntimeError("exchange_calendars unavailable") from exc
    return xcals.get_calendar("XSHG")


def _session_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date"):
        result = value.date()
        if isinstance(result, date):
            return result
    raise TypeError("calendar session cannot be converted to date")


def _parse_provider_label(value: object) -> datetime | None:
    raw = str(value or "").strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M").replace(tzinfo=CN)
    except ValueError:
        return None


def _boundary_datetimes(session_date: date, interval_minutes: int) -> tuple[datetime, ...]:
    return tuple(
        datetime.combine(
            session_date,
            time.fromisoformat(label),
            tzinfo=CN,
        )
        for label in END_BOUNDARIES[interval_minutes]
    )


def expected_latest_completed_boundary(
    *,
    interval_minutes: int,
    observed_at_utc: datetime,
    completion_grace_seconds: int = 30,
    session_calendar: SessionCalendar | None = None,
) -> datetime:
    """Return the latest provider-neutral completed A-share BAR_END boundary.

    A small grace window prevents a just-closed interval from becoming
    mandatory before a provider has a reasonable chance to publish it.
    """

    if interval_minutes not in SUPPORTED_INTERVALS:
        raise ValueError("interval_minutes must be 15 or 60")
    if observed_at_utc.tzinfo is None or observed_at_utc.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    if completion_grace_seconds < 0 or completion_grace_seconds > 300:
        raise ValueError("completion_grace_seconds must be between 0 and 300")

    cal = session_calendar or _calendar()
    observed_local = observed_at_utc.astimezone(CN)
    cutoff = observed_local - timedelta(seconds=completion_grace_seconds)
    local_date = observed_local.date()

    try:
        today_is_session = bool(cal.is_session(local_date))
    except Exception as exc:
        raise RuntimeError("calendar session lookup failed") from exc

    if today_is_session:
        today_boundaries = _boundary_datetimes(local_date, interval_minutes)
        completed = tuple(boundary for boundary in today_boundaries if boundary <= cutoff)
        if completed:
            return completed[-1]
        lookup_date = local_date - timedelta(days=1)
    else:
        lookup_date = local_date

    try:
        previous = cal.date_to_session(lookup_date, direction="previous")
    except Exception as exc:
        raise RuntimeError("previous trading session lookup failed") from exc
    previous_date = _session_date(previous)
    return _boundary_datetimes(previous_date, interval_minutes)[-1]


def qualify_cn_intraday_currentness(
    provider_label: object,
    *,
    interval_minutes: int,
    observed_at_utc: datetime,
    timestamp_semantic: str,
    timestamp_qualification_status: str,
    completion_grace_seconds: int = 30,
    session_calendar: SessionCalendar | None = None,
) -> CnIntradayCurrentnessResult:
    """Classify provider Currentness after independent BAR_END qualification."""

    if observed_at_utc.tzinfo is None or observed_at_utc.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    observed = observed_at_utc.astimezone(timezone.utc)
    semantic = str(timestamp_semantic or "").strip().upper()
    qualification = str(timestamp_qualification_status or "").strip().upper()

    if semantic != "BAR_END" or qualification != "PASS":
        return CnIntradayCurrentnessResult(
            status="UNKNOWN",
            reason="TIMESTAMP_SEMANTICS_NOT_QUALIFIED",
            interval_minutes=interval_minutes,
            provider_label=str(provider_label or "").strip() or None,
            expected_label=None,
            observed_at_utc=observed,
            session_date=None,
            timestamp_semantic=semantic or "UNKNOWN",
            timestamp_qualification_status=qualification or "UNKNOWN",
        )

    if interval_minutes not in SUPPORTED_INTERVALS:
        return CnIntradayCurrentnessResult(
            status="FAIL",
            reason="UNSUPPORTED_INTERVAL",
            interval_minutes=interval_minutes,
            provider_label=str(provider_label or "").strip() or None,
            expected_label=None,
            observed_at_utc=observed,
            session_date=None,
        )

    parsed = _parse_provider_label(provider_label)
    if parsed is None:
        return CnIntradayCurrentnessResult(
            status="FAIL",
            reason="INVALID_PROVIDER_LABEL",
            interval_minutes=interval_minutes,
            provider_label=str(provider_label or "").strip() or None,
            expected_label=None,
            observed_at_utc=observed,
            session_date=None,
        )

    if parsed.strftime("%H:%M") not in END_BOUNDARIES[interval_minutes]:
        return CnIntradayCurrentnessResult(
            status="FAIL",
            reason="PROVIDER_LABEL_OFF_ADMITTED_GRID",
            interval_minutes=interval_minutes,
            provider_label=parsed.strftime("%Y-%m-%d %H:%M"),
            expected_label=None,
            observed_at_utc=observed,
            session_date=parsed.date().isoformat(),
        )

    cal = session_calendar or _calendar()
    try:
        if not bool(cal.is_session(parsed.date())):
            return CnIntradayCurrentnessResult(
                status="FAIL",
                reason="PROVIDER_LABEL_ON_NON_TRADING_DATE",
                interval_minutes=interval_minutes,
                provider_label=parsed.strftime("%Y-%m-%d %H:%M"),
                expected_label=None,
                observed_at_utc=observed,
                session_date=parsed.date().isoformat(),
            )
        expected = expected_latest_completed_boundary(
            interval_minutes=interval_minutes,
            observed_at_utc=observed,
            completion_grace_seconds=completion_grace_seconds,
            session_calendar=cal,
        )
    except Exception as exc:
        return CnIntradayCurrentnessResult(
            status="UNKNOWN",
            reason=f"CALENDAR_EVIDENCE_UNAVAILABLE:{type(exc).__name__}",
            interval_minutes=interval_minutes,
            provider_label=parsed.strftime("%Y-%m-%d %H:%M"),
            expected_label=None,
            observed_at_utc=observed,
            session_date=None,
        )

    provider_text = parsed.strftime("%Y-%m-%d %H:%M")
    expected_text = expected.strftime("%Y-%m-%d %H:%M")
    if parsed == expected:
        return CnIntradayCurrentnessResult(
            status="PASS",
            reason="LATEST_COMPLETED_BOUNDARY_MATCH",
            interval_minutes=interval_minutes,
            provider_label=provider_text,
            expected_label=expected_text,
            observed_at_utc=observed,
            session_date=expected.date().isoformat(),
        )
    if parsed < expected:
        reason = "EXPECTED_COMPLETED_BOUNDARY_NOT_REACHED"
    else:
        reason = "PROVIDER_LABEL_AHEAD_OF_EXPECTED_BOUNDARY"
    return CnIntradayCurrentnessResult(
        status="FAIL",
        reason=reason,
        interval_minutes=interval_minutes,
        provider_label=provider_text,
        expected_label=expected_text,
        observed_at_utc=observed,
        session_date=expected.date().isoformat(),
    )

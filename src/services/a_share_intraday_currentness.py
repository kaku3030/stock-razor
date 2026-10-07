"""Fail-closed same-session Currentness qualification for A-share intraday bars.

This module can prove only that a BAR_END-labeled intraday stream has reached
the latest completed regular-session boundary on the same Shanghai trading
date as the observation. It intentionally does not infer holiday calendars,
cross-day freshness, continuity, Radar admission, or execution permission.

Consequences:
- on weekends/holidays, prior-session bars remain BLOCKED;
- before the first completed intraday boundary, Currentness remains BLOCKED;
- after a valid same-day boundary, exact boundary alignment can be PROVEN.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.services.a_share_intraday_semantics import (
    CN_MARKET_TIMEZONE,
    CN_REGULAR_SESSION_SEGMENTS,
    TimestampSemantic,
)


_SUPPORTED_INTERVALS = frozenset({15, 60})


@dataclass(frozen=True)
class AShareIntradayCurrentnessQualification:
    status: str
    interval_minutes: int
    timestamp_semantic: TimestampSemantic
    observed_at_market_local: str
    latest_provider_label: str | None
    expected_completed_boundary: str | None
    reasons: tuple[str, ...] = ()
    currentness_proven: bool = field(default=False)
    continuity_proven: bool = field(default=False, init=False)
    radar_admission: str = field(default="BLOCKED", init=False)
    live_trade: bool = field(default=False, init=False)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["timestamp_semantic"] = self.timestamp_semantic.value
        payload["reasons"] = list(self.reasons)
        return payload


def _parse_clock(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def expected_regular_session_end_labels(
    session_date: date,
    *,
    interval_minutes: int,
) -> tuple[datetime, ...]:
    """Build canonical BAR_END boundaries from the governed A-share session."""

    if interval_minutes not in _SUPPORTED_INTERVALS:
        raise ValueError("interval_minutes must be 15 or 60")

    tz = ZoneInfo(CN_MARKET_TIMEZONE)
    boundaries: list[datetime] = []
    step = timedelta(minutes=interval_minutes)

    for raw_start, raw_end in CN_REGULAR_SESSION_SEGMENTS:
        start = datetime.combine(session_date, _parse_clock(raw_start), tzinfo=tz)
        end = datetime.combine(session_date, _parse_clock(raw_end), tzinfo=tz)
        cursor = start + step
        while cursor <= end:
            boundaries.append(cursor)
            cursor += step

    return tuple(boundaries)


def qualify_same_session_currentness(
    latest_provider_label: str | None,
    *,
    interval_minutes: int,
    timestamp_semantic: TimestampSemantic,
    observed_at: datetime,
) -> AShareIntradayCurrentnessQualification:
    """Prove same-session Currentness only from exact completed BAR_END alignment."""

    if interval_minutes not in _SUPPORTED_INTERVALS:
        raise ValueError("interval_minutes must be 15 or 60")
    if not isinstance(timestamp_semantic, TimestampSemantic):
        raise ValueError("timestamp_semantic must be TimestampSemantic")
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")

    market_tz = ZoneInfo(CN_MARKET_TIMEZONE)
    local_now = observed_at.astimezone(market_tz)

    if timestamp_semantic is not TimestampSemantic.BAR_END:
        return _blocked(
            interval_minutes,
            timestamp_semantic,
            local_now,
            latest_provider_label,
            reasons=("TIMESTAMP_SEMANTIC_NOT_BAR_END",),
        )

    if not latest_provider_label:
        return _blocked(
            interval_minutes,
            timestamp_semantic,
            local_now,
            None,
            reasons=("MISSING_PROVIDER_LABEL",),
        )

    try:
        latest_naive = datetime.strptime(
            str(latest_provider_label),
            "%Y-%m-%d %H:%M",
        )
    except ValueError:
        return _blocked(
            interval_minutes,
            timestamp_semantic,
            local_now,
            str(latest_provider_label),
            reasons=("PROVIDER_LABEL_PARSE_ERROR",),
        )

    latest = latest_naive.replace(tzinfo=market_tz)
    boundaries = expected_regular_session_end_labels(
        local_now.date(),
        interval_minutes=interval_minutes,
    )
    boundary_set = set(boundaries)

    # A previous-session label on a holiday/weekend/premarket can be valid
    # historical data, but it cannot establish same-session Currentness.
    if latest.date() != local_now.date():
        return _blocked(
            interval_minutes,
            timestamp_semantic,
            local_now,
            latest_provider_label,
            reasons=("LATEST_LABEL_NOT_OBSERVATION_DATE",),
        )

    if latest not in boundary_set:
        return _blocked(
            interval_minutes,
            timestamp_semantic,
            local_now,
            latest_provider_label,
            reasons=("TIMESTAMP_OFF_ADMITTED_GRID",),
        )

    completed = tuple(boundary for boundary in boundaries if boundary <= local_now)
    if not completed:
        return _blocked(
            interval_minutes,
            timestamp_semantic,
            local_now,
            latest_provider_label,
            reasons=("NO_COMPLETED_INTRADAY_BOUNDARY",),
        )

    expected = completed[-1]
    if latest < expected:
        return _blocked(
            interval_minutes,
            timestamp_semantic,
            local_now,
            latest_provider_label,
            expected=expected,
            reasons=("EXPECTED_COMPLETED_BOUNDARY_NOT_REACHED",),
        )
    if latest > expected:
        return _blocked(
            interval_minutes,
            timestamp_semantic,
            local_now,
            latest_provider_label,
            expected=expected,
            reasons=("PROVIDER_TIMESTAMP_AHEAD_OF_EXPECTED_BOUNDARY",),
        )

    return AShareIntradayCurrentnessQualification(
        status="PASS",
        interval_minutes=interval_minutes,
        timestamp_semantic=timestamp_semantic,
        observed_at_market_local=local_now.isoformat(),
        latest_provider_label=latest_provider_label,
        expected_completed_boundary=expected.isoformat(),
        reasons=(),
        currentness_proven=True,
    )


def _blocked(
    interval_minutes: int,
    timestamp_semantic: TimestampSemantic,
    local_now: datetime,
    latest_provider_label: str | None,
    *,
    expected: datetime | None = None,
    reasons: tuple[str, ...],
) -> AShareIntradayCurrentnessQualification:
    return AShareIntradayCurrentnessQualification(
        status="BLOCKED",
        interval_minutes=interval_minutes,
        timestamp_semantic=timestamp_semantic,
        observed_at_market_local=local_now.isoformat(),
        latest_provider_label=latest_provider_label,
        expected_completed_boundary=expected.isoformat() if expected else None,
        reasons=reasons,
        currentness_proven=False,
    )

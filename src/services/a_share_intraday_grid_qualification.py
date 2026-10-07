"""Historical grid qualification for A-share intraday timestamp semantics.

This module may prove a provider label convention from repeated complete
regular-session grids. It does NOT prove Currentness, freshness, continuity,
Radar admission, or execution permission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Sequence

from src.services.a_share_intraday_semantics import (
    CN_INTRADAY_ENDPOINT_EXTENSIONS,
    TimestampSemantic,
)
from src.services.a_share_provider_lineage import CN_REALTIME_SOURCE_LINEAGE


_EXPECTED_END_LABELS = {
    15: (
        "09:45", "10:00", "10:15", "10:30",
        "10:45", "11:00", "11:15", "11:30",
        "13:15", "13:30", "13:45", "14:00",
        "14:15", "14:30", "14:45", "15:00",
    ),
    60: ("10:30", "11:30", "14:00", "15:00"),
}


@dataclass(frozen=True)
class IntradayTimestampGridQualification:
    status: str
    source_token: str
    endpoint_id: str
    interval_minutes: int
    timestamp_semantic: TimestampSemantic
    complete_session_dates: tuple[str, ...]
    sessions_examined: int
    labels_examined: int
    reasons: tuple[str, ...] = ()
    currentness_proven: bool = field(default=False, init=False)
    continuity_proven: bool = field(default=False, init=False)
    radar_admission: str = field(default="BLOCKED", init=False)
    live_trade: bool = field(default=False, init=False)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["timestamp_semantic"] = self.timestamp_semantic.value
        payload["complete_session_dates"] = list(self.complete_session_dates)
        payload["reasons"] = list(self.reasons)
        return payload


def qualify_intraday_end_label_grid(
    labels: Sequence[str],
    *,
    source_token: str,
    endpoint_id: str,
    interval_minutes: int,
    minimum_complete_sessions: int = 3,
) -> IntradayTimestampGridQualification:
    """Prove BAR_END only from repeated exact regular-session label grids."""

    source = str(source_token or "").strip()
    endpoint = str(endpoint_id or "").strip()
    expected = _EXPECTED_END_LABELS.get(interval_minutes)
    if expected is None:
        raise ValueError("interval_minutes must be 15 or 60")
    if minimum_complete_sessions < 2:
        raise ValueError("minimum_complete_sessions must be at least 2")

    lineage = CN_REALTIME_SOURCE_LINEAGE.get(source)
    if lineage is None or lineage.upstream_lineage_id != "tencent":
        return _blocked(
            source, endpoint, interval_minutes, labels,
            reasons=("UNSUPPORTED_SOURCE_LINEAGE",),
        )
    allowed = CN_INTRADAY_ENDPOINT_EXTENSIONS.get(source, frozenset())
    if endpoint not in allowed:
        return _blocked(
            source, endpoint, interval_minutes, labels,
            reasons=("INVALID_INTRADAY_ENDPOINT_BINDING",),
        )

    parsed: list[datetime] = []
    for raw in labels:
        try:
            parsed.append(datetime.strptime(str(raw), "%Y-%m-%d %H:%M"))
        except ValueError:
            return _blocked(
                source, endpoint, interval_minutes, labels,
                reasons=("LABEL_PARSE_ERROR",),
            )

    if not parsed:
        return _blocked(
            source, endpoint, interval_minutes, labels,
            reasons=("NO_LABELS",),
        )
    if parsed != sorted(parsed) or len(parsed) != len(set(parsed)):
        return _blocked(
            source, endpoint, interval_minutes, labels,
            reasons=("LABELS_NOT_STRICTLY_INCREASING",),
        )

    by_date: dict[str, list[str]] = {}
    for stamp in parsed:
        by_date.setdefault(stamp.date().isoformat(), []).append(stamp.strftime("%H:%M"))

    complete: list[str] = []
    expected_set = set(expected)
    for session_date, times in by_date.items():
        if any(value not in expected_set for value in times):
            return _blocked(
                source, endpoint, interval_minutes, labels,
                sessions_examined=len(by_date),
                reasons=(f"{session_date}:UNEXPECTED_SESSION_LABEL",),
            )
        if len(times) == len(expected):
            if tuple(times) != expected:
                return _blocked(
                    source, endpoint, interval_minutes, labels,
                    sessions_examined=len(by_date),
                    reasons=(f"{session_date}:GRID_ORDER_MISMATCH",),
                )
            complete.append(session_date)
        elif len(times) > len(expected):
            return _blocked(
                source, endpoint, interval_minutes, labels,
                sessions_examined=len(by_date),
                reasons=(f"{session_date}:TOO_MANY_LABELS",),
            )

    if len(complete) < minimum_complete_sessions:
        return _blocked(
            source, endpoint, interval_minutes, labels,
            sessions_examined=len(by_date),
            complete_session_dates=tuple(complete),
            reasons=("INSUFFICIENT_COMPLETE_SESSIONS",),
        )

    return IntradayTimestampGridQualification(
        status="PASS",
        source_token=source,
        endpoint_id=endpoint,
        interval_minutes=interval_minutes,
        timestamp_semantic=TimestampSemantic.BAR_END,
        complete_session_dates=tuple(complete),
        sessions_examined=len(by_date),
        labels_examined=len(labels),
        reasons=(),
    )


def _blocked(
    source_token: str,
    endpoint_id: str,
    interval_minutes: int,
    labels: Sequence[str],
    *,
    sessions_examined: int = 0,
    complete_session_dates: tuple[str, ...] = (),
    reasons: tuple[str, ...],
) -> IntradayTimestampGridQualification:
    return IntradayTimestampGridQualification(
        status="BLOCKED",
        source_token=source_token,
        endpoint_id=endpoint_id,
        interval_minutes=interval_minutes,
        timestamp_semantic=TimestampSemantic.UNKNOWN,
        complete_session_dates=complete_session_dates,
        sessions_examined=sessions_examined,
        labels_examined=len(labels),
        reasons=reasons,
    )

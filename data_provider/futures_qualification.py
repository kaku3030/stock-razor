"""Fail-closed futures currentness evidence for the existing LiveFeed harness.

This module does not establish realtime entitlement.  It only validates the
provider facts needed before a futures ``ProviderEvent`` can be consumed by
the existing two-phase qualification semantics.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from enum import Enum
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from data_provider.futures_provider import FUTURES_INSTRUMENTS
from data_provider.live_feed_types import ProviderEvent


class FuturesSessionPhase(str, Enum):
    ACTIVE_SESSION = "ACTIVE_SESSION"
    EXPECTED_SILENCE = "EXPECTED_SILENCE"
    CLOSED_SESSION = "CLOSED_SESSION"


@dataclass(frozen=True)
class FuturesSessionPolicy:
    """Conservative CME-style session boundary policy.

    The holiday set must come from an independently verified exchange
    calendar.  An unverified calendar never proves currentness.
    """

    timezone_name: str = "America/New_York"
    holidays: frozenset[date] = frozenset()
    holiday_calendar_verified: bool = False

    def phase(self, at_utc: datetime) -> FuturesSessionPhase:
        local = _aware_utc(at_utc).astimezone(ZoneInfo(self.timezone_name))
        if local.date() in self.holidays:
            return FuturesSessionPhase.CLOSED_SESSION
        # Sunday opens at 18:00 ET; Saturday is fully closed.  Each open day
        # has the standard 17:00-18:00 ET maintenance break.
        if local.weekday() == 5:
            return FuturesSessionPhase.CLOSED_SESSION
        if local.weekday() == 6 and local.time() < time(18, 0):
            return FuturesSessionPhase.CLOSED_SESSION
        if local.weekday() == 4 and local.time() >= time(17, 0):
            return FuturesSessionPhase.CLOSED_SESSION
        if time(17, 0) <= local.time() < time(18, 0):
            return FuturesSessionPhase.EXPECTED_SILENCE
        return FuturesSessionPhase.ACTIVE_SESSION


@dataclass(frozen=True)
class FuturesCurrentnessDecision:
    passed: bool
    reason: str
    provider_timestamp: datetime | None = None
    age_seconds: float | None = None
    session_phase: FuturesSessionPhase | None = None


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _provider_timestamp(event: ProviderEvent, payload: Mapping[str, Any]) -> datetime | None:
    value = payload.get("provider_timestamp", event.provider_timestamp_raw)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def evaluate_futures_currentness(
    event: ProviderEvent,
    *,
    now_utc: datetime,
    session_policy: FuturesSessionPolicy,
    max_age_seconds: int = 900,
) -> FuturesCurrentnessDecision:
    """Evaluate intraday futures evidence without asserting realtime delivery."""

    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    now = _aware_utc(now_utc)
    key = event.semantic_stream_key
    payload = event.payload or {}
    if key is None or key.market.upper() != "US_FUTURES":
        return FuturesCurrentnessDecision(False, "INVALID_FUTURES_STREAM")
    if key.symbol.upper() not in FUTURES_INSTRUMENTS:
        return FuturesCurrentnessDecision(False, "UNSUPPORTED_FUTURES_ROOT")
    if key.timeframe not in {"1m", "5m", "15m", "1h"}:
        return FuturesCurrentnessDecision(False, "NON_INTRADAY_NOT_LIVE_QUALIFIABLE")
    if payload.get("volume") is None:
        return FuturesCurrentnessDecision(False, "MISSING_VOLUME")
    if payload.get("instrument_root", "").upper() != key.symbol.upper() or not payload.get("exchange"):
        return FuturesCurrentnessDecision(False, "MISSING_CONTRACT_METADATA")
    if payload.get("volume_semantics") != "contracts":
        return FuturesCurrentnessDecision(False, "MISSING_CONTRACT_METADATA")
    try:
        volume = float(payload["volume"])
    except (TypeError, ValueError):
        return FuturesCurrentnessDecision(False, "INVALID_VOLUME")
    if not math.isfinite(volume) or volume < 0:
        return FuturesCurrentnessDecision(False, "INVALID_VOLUME")
    feed = key.feed
    if feed == "actual_contract":
        if not payload.get("contract_symbol") or not payload.get("contract_month"):
            return FuturesCurrentnessDecision(False, "MISSING_CONTRACT_METADATA")
        if payload.get("continuous_semantics") != "explicit_actual_contract":
            return FuturesCurrentnessDecision(False, "AMBIGUOUS_ROLL_OR_FEED")
    elif feed != "vendor_continuous":
        return FuturesCurrentnessDecision(False, "AMBIGUOUS_ROLL_OR_FEED")
    elif payload.get("continuous_semantics") != "vendor_continuous_candidate":
        return FuturesCurrentnessDecision(False, "AMBIGUOUS_ROLL_OR_FEED")

    provider_timestamp = _provider_timestamp(event, payload)
    if provider_timestamp is None:
        return FuturesCurrentnessDecision(False, "MISSING_OR_NAIVE_TIMESTAMP")
    age = (now - provider_timestamp).total_seconds()
    if age < 0:
        return FuturesCurrentnessDecision(False, "PROVIDER_TIMESTAMP_IN_FUTURE", provider_timestamp, age)
    if age > max_age_seconds:
        return FuturesCurrentnessDecision(False, "STALE_PROVIDER_OBSERVATION", provider_timestamp, age)
    if not session_policy.holiday_calendar_verified:
        return FuturesCurrentnessDecision(False, "SESSION_CALENDAR_UNVERIFIED", provider_timestamp, age)
    now_phase = session_policy.phase(now)
    source_phase = session_policy.phase(provider_timestamp)
    if now_phase is not FuturesSessionPhase.ACTIVE_SESSION or source_phase is not FuturesSessionPhase.ACTIVE_SESSION:
        return FuturesCurrentnessDecision(False, "SESSION_CLOSED_OR_BREAK", provider_timestamp, age, now_phase)
    return FuturesCurrentnessDecision(True, "CURRENTNESS_PROVEN_CANDIDATE", provider_timestamp, age, now_phase)

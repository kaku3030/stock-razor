from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


US_EASTERN = ZoneInfo("America/New_York")
REGULAR_MARKET_STATES = frozenset({"MORNING", "AFTERNOON"})
EXTENDED_MARKET_STATES = frozenset({
    "PRE_MARKET_BEGIN",
    "PRE_MARKET_END",
    "AFTER_HOURS_BEGIN",
    "AFTER_HOURS_END",
    "OVERNIGHT",
})
CLOSED_MARKET_STATES = frozenset({"CLOSED", "WAITING_OPEN", "NONE"})


def futu_us_market_state_to_session(market_state: str | None) -> str:
    """Map Futu US market-state evidence into cache session vocabulary.

    Unknown/new provider states remain unknown rather than being guessed
    into an active session. This helper is classification only; it does not
    prove realtime delivery or admit Radar.
    """

    state = str(market_state or "UNKNOWN").strip().upper() or "UNKNOWN"
    if state in REGULAR_MARKET_STATES:
        return "regular"
    if state in {"PRE_MARKET_BEGIN", "PRE_MARKET_END"}:
        return "premarket"
    if state in {"AFTER_HOURS_BEGIN", "AFTER_HOURS_END"}:
        return "afterhours"
    if state == "OVERNIGHT":
        return "overnight"
    if state in CLOSED_MARKET_STATES:
        return "closed"
    return "unknown"


@dataclass(frozen=True)
class FutuK1MCurrentnessResult:
    status: str
    reason: str
    market_state: str
    source_time_utc: datetime | None = None
    interval_start_utc: datetime | None = None
    interval_end_utc: datetime | None = None
    observed_at_utc: datetime | None = None
    age_seconds: float | None = None
    end_offset_seconds: float | None = None
    delivery_mode: str = "UNKNOWN"
    radar_admission: str = "BLOCKED"
    live_trade: bool = False

    @property
    def can_promote(self) -> bool:
        return False


def classify_futu_us_k1m_currentness(
    time_key: str | None,
    *,
    observed_at_utc: datetime,
    market_state: str | None,
    max_regular_lag_seconds: int = 120,
    max_interval_start_skew_seconds: int = 5,
) -> FutuK1MCurrentnessResult:
    """Classify K_1M currentness without promoting delivery or trading.

    US OpenD K-line ``time_key`` is exchange-local US Eastern time and
    Futu intraday K_1M labels are provider interval-END labels. A label 09:49
    represents the forming interval [09:48, 09:49), so it is expected to be
    ahead of wall-clock time while that minute is still forming. Currentness
    therefore evaluates interval coverage first, then post-close lag. Extended
    hours and closed-session K_1M currentness remain NOT_APPLICABLE.
    """

    if observed_at_utc.tzinfo is None or observed_at_utc.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    if max_regular_lag_seconds <= 0:
        raise ValueError("max_regular_lag_seconds must be positive")
    if max_interval_start_skew_seconds < 0:
        raise ValueError("max_interval_start_skew_seconds must be non-negative")

    state = str(market_state or "UNKNOWN").strip().upper() or "UNKNOWN"
    observed = observed_at_utc.astimezone(timezone.utc)

    if state in EXTENDED_MARKET_STATES:
        return FutuK1MCurrentnessResult(
            status="NOT_APPLICABLE",
            reason="EXTENDED_SESSION_K1M_CURRENTNESS_UNQUALIFIED",
            market_state=state,
            observed_at_utc=observed,
        )
    if state in CLOSED_MARKET_STATES:
        return FutuK1MCurrentnessResult(
            status="NOT_APPLICABLE",
            reason="MARKET_NOT_REGULAR_SESSION",
            market_state=state,
            observed_at_utc=observed,
        )
    if state not in REGULAR_MARKET_STATES:
        return FutuK1MCurrentnessResult(
            status="UNKNOWN",
            reason="UNRECOGNIZED_US_MARKET_STATE",
            market_state=state,
            observed_at_utc=observed,
        )

    raw = str(time_key or "").strip()
    try:
        local = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=US_EASTERN)
    except ValueError:
        return FutuK1MCurrentnessResult(
            status="FAIL",
            reason="INVALID_K1M_TIME_KEY",
            market_state=state,
            observed_at_utc=observed,
        )

    interval_end = local.astimezone(timezone.utc)
    interval_start = interval_end - timedelta(minutes=1)
    start_offset = (observed - interval_start).total_seconds()
    end_offset = (observed - interval_end).total_seconds()

    if start_offset < -max_interval_start_skew_seconds:
        return FutuK1MCurrentnessResult(
            status="FAIL",
            reason="K1M_INTERVAL_NOT_STARTED",
            market_state=state,
            source_time_utc=interval_end,
            interval_start_utc=interval_start,
            interval_end_utc=interval_end,
            observed_at_utc=observed,
            end_offset_seconds=end_offset,
        )

    if start_offset < 0:
        return FutuK1MCurrentnessResult(
            status="PASS",
            reason="K1M_INTERVAL_START_WITHIN_CLOCK_SKEW",
            market_state=state,
            source_time_utc=interval_end,
            interval_start_utc=interval_start,
            interval_end_utc=interval_end,
            observed_at_utc=observed,
            age_seconds=0.0,
            end_offset_seconds=end_offset,
        )

    if end_offset <= 0:
        return FutuK1MCurrentnessResult(
            status="PASS",
            reason="K1M_FORMING_INTERVAL_COVERS_OBSERVATION",
            market_state=state,
            source_time_utc=interval_end,
            interval_start_utc=interval_start,
            interval_end_utc=interval_end,
            observed_at_utc=observed,
            age_seconds=0.0,
            end_offset_seconds=end_offset,
        )

    if end_offset > max_regular_lag_seconds:
        return FutuK1MCurrentnessResult(
            status="FAIL",
            reason="K1M_STALE_DURING_REGULAR_SESSION",
            market_state=state,
            source_time_utc=interval_end,
            interval_start_utc=interval_start,
            interval_end_utc=interval_end,
            observed_at_utc=observed,
            age_seconds=end_offset,
            end_offset_seconds=end_offset,
        )

    return FutuK1MCurrentnessResult(
        status="PASS",
        reason="K1M_WITHIN_REGULAR_SESSION_LAG_BUDGET",
        market_state=state,
        source_time_utc=interval_end,
        interval_start_utc=interval_start,
        interval_end_utc=interval_end,
        observed_at_utc=observed,
        age_seconds=end_offset,
        end_offset_seconds=end_offset,
    )


def summarize_futu_k1m_currentness(results: dict[str, FutuK1MCurrentnessResult]) -> str:
    if not results:
        return "UNKNOWN"
    statuses = [result.status for result in results.values()]
    if any(status == "FAIL" for status in statuses):
        return "FAIL"
    if all(status == "PASS" for status in statuses):
        return "PASS"
    if all(status == "NOT_APPLICABLE" for status in statuses):
        return "NOT_APPLICABLE"
    return "UNKNOWN"

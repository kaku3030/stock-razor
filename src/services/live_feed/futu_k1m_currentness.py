from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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
    observed_at_utc: datetime | None = None
    age_seconds: float | None = None
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
    max_forming_end_label_lead_seconds: int = 65,
) -> FutuK1MCurrentnessResult:
    """Classify K_1M currentness without promoting delivery or trading.

    US OpenD K-line ``time_key`` is exchange-local US Eastern time and,
    for intraday K-lines, empirically labels the interval END. During a live
    minute the provider may therefore publish the forming minute's end label
    up to about 60 seconds ahead of wall clock. That bounded lead is valid
    currentness evidence only; it does not prove bar closure or delivery mode.
    Extended-hours and closed-session K_1M currentness are deliberately not
    inferred from a cached push; they remain NOT_APPLICABLE for realtime
    qualification.
    """

    if observed_at_utc.tzinfo is None or observed_at_utc.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    if max_regular_lag_seconds <= 0:
        raise ValueError("max_regular_lag_seconds must be positive")
    if max_forming_end_label_lead_seconds < 60:
        raise ValueError(
            "max_forming_end_label_lead_seconds must cover one full minute"
        )

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

    source = local.astimezone(timezone.utc)
    age = (observed - source).total_seconds()
    if age < -max_forming_end_label_lead_seconds:
        return FutuK1MCurrentnessResult(
            status="FAIL",
            reason="K1M_TIME_KEY_BEYOND_FORMING_END_LABEL_WINDOW",
            market_state=state,
            source_time_utc=source,
            observed_at_utc=observed,
            age_seconds=age,
        )
    if age > max_regular_lag_seconds:
        return FutuK1MCurrentnessResult(
            status="FAIL",
            reason="K1M_STALE_DURING_REGULAR_SESSION",
            market_state=state,
            source_time_utc=source,
            observed_at_utc=observed,
            age_seconds=age,
        )
    return FutuK1MCurrentnessResult(
        status="PASS",
        reason=(
            "K1M_FORMING_END_LABEL_WITHIN_EXPECTED_WINDOW"
            if age < 0
            else "K1M_WITHIN_REGULAR_SESSION_LAG_BUDGET"
        ),
        market_state=state,
        source_time_utc=source,
        observed_at_utc=observed,
        age_seconds=age,
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

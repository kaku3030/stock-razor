from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from math import isfinite
from typing import Mapping, Sequence


FUTU_US_K1M_REGULAR_SESSION_ROWS = 390
FUTU_US_K1M_FIRST_END_LABEL = time(9, 31)
FUTU_US_K1M_LAST_END_LABEL = time(16, 0)


@dataclass(frozen=True)
class FutuK1MHistoryQualification:
    status: str
    symbol: str
    session_date: str | None
    row_count: int
    first_time_key: str | None
    last_time_key: str | None
    reasons: tuple[str, ...] = ()
    expected_row_count: int = FUTU_US_K1M_REGULAR_SESSION_ROWS
    timestamp_semantics: str = "INTERVAL_END_PROVEN_US_K1M"
    session_timezone: str = "America/New_York"
    purpose: str = "RESEARCH_CACHE_WARM_START_QUALIFICATION"
    historical_query: bool = True
    realtime_currentness_proven: bool = False
    bar_closure_promotion_authorized: bool = False
    radar_admission: str = "BLOCKED"
    live_trade: bool = False

    @property
    def research_cache_seed_eligible(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["research_cache_seed_eligible"] = self.research_cache_seed_eligible
        payload["reasons"] = list(self.reasons)
        return payload


def _parse_time_key(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _expected_end_labels(session_date: date) -> tuple[datetime, ...]:
    first = datetime.combine(session_date, FUTU_US_K1M_FIRST_END_LABEL)
    return tuple(
        first + timedelta(minutes=offset)
        for offset in range(FUTU_US_K1M_REGULAR_SESSION_ROWS)
    )


def qualify_futu_us_k1m_history(
    rows: Sequence[Mapping[str, object]],
    *,
    expected_symbol: str,
    expected_session_date: date | None = None,
) -> FutuK1MHistoryQualification:
    """Qualify one completed regular-session OpenD K_1M history grid.

    This function validates historical facts only. A PASS means the rows are
    structurally eligible to seed a *research* cache. It does not prove
    realtime currentness, provider delivery mode, live closure progression,
    Radar admission, or trading authority.
    """

    symbol = str(expected_symbol or "").strip().upper()
    if not symbol.startswith("US."):
        raise ValueError("expected_symbol must use canonical US.* form")

    materialized = [dict(row) for row in rows]
    reasons: list[str] = []
    parsed: list[datetime] = []

    if not materialized:
        reasons.append("NO_ROWS")

    for row in materialized:
        row_symbol = str(row.get("code") or "").strip().upper()
        if row_symbol != symbol:
            reasons.append("SYMBOL_MISMATCH")

        stamp = _parse_time_key(row.get("time_key"))
        if stamp is None:
            reasons.append("TIME_KEY_PARSE_ERROR")
        else:
            parsed.append(stamp)

        open_ = _finite_number(row.get("open"))
        high = _finite_number(row.get("high"))
        low = _finite_number(row.get("low"))
        close = _finite_number(row.get("close"))
        if (
            open_ is None
            or high is None
            or low is None
            or close is None
            or min(open_, high, low, close) <= 0
            or high < low
            or high < max(open_, close)
            or low > min(open_, close)
        ):
            reasons.append("INVALID_OHLC")

        volume = _finite_number(row.get("volume"))
        if volume is None:
            reasons.append("INVALID_VOLUME")
        elif volume < 0:
            reasons.append("NEGATIVE_VOLUME")

        turnover_raw = row.get("turnover")
        if turnover_raw is not None:
            turnover = _finite_number(turnover_raw)
            if turnover is None:
                reasons.append("INVALID_TURNOVER")
            elif turnover < 0:
                reasons.append("NEGATIVE_TURNOVER")

    session_date: date | None = expected_session_date
    if parsed:
        parsed_dates = {stamp.date() for stamp in parsed}
        if len(parsed_dates) != 1:
            reasons.append("MULTI_SESSION_ROWS")
        observed_date = parsed[0].date()
        if session_date is None:
            session_date = observed_date
        elif observed_date != session_date or any(
            stamp.date() != session_date for stamp in parsed
        ):
            reasons.append("SESSION_DATE_MISMATCH")

        if len(set(parsed)) != len(parsed):
            reasons.append("DUPLICATE_TIME_KEY")
        if parsed != sorted(parsed):
            reasons.append("OUT_OF_ORDER_TIME_KEY")

    if session_date is not None:
        expected = _expected_end_labels(session_date)
        if tuple(parsed) != expected:
            reasons.append("REGULAR_SESSION_GRID_INCOMPLETE")

    first_time_key = (
        parsed[0].strftime("%Y-%m-%d %H:%M:%S") if parsed else None
    )
    last_time_key = (
        parsed[-1].strftime("%Y-%m-%d %H:%M:%S") if parsed else None
    )
    unique_reasons = tuple(dict.fromkeys(reasons))

    return FutuK1MHistoryQualification(
        status="PASS" if not unique_reasons else "BLOCKED",
        symbol=symbol,
        session_date=session_date.isoformat() if session_date is not None else None,
        row_count=len(materialized),
        first_time_key=first_time_key,
        last_time_key=last_time_key,
        reasons=unique_reasons,
    )

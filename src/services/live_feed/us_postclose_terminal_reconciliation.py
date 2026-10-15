"""Bounded, fail-closed OpenD US RTH terminal-minute historical reconciliation.

The live push accumulator requires a later provider end label to close the
15:59 ET time_key. A 16:00 label may never arrive in the live stream;
never pretend an after-hours transition is provider proof:
only an independent 390-row same-OpenD historical RTH grid observed after
16:30 ET can supply that final minute, marked HISTORICAL_QUERY.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Callable, Mapping, Protocol, Sequence
from zoneinfo import ZoneInfo

from .futu_k1m_history import normalize_futu_k1m_history_rows

EASTERN = ZoneInfo("America/New_York")
POSTCLOSE_BUFFER_END = time(16, 30)
POSTCLOSE_MARKET_STATES = frozenset({
    "AFTER_HOURS_BEGIN", "AFTER_HOURS_END", "OVERNIGHT", "CLOSED", "WAITING_OPEN",
})
MAX_SYMBOLS = 20


def postclose_history_retry_due(
    *,
    attempts: int,
    last_attempt_at: datetime | None,
    observed_at: datetime,
    prior_status: str,
) -> bool:
    """Maximum two same-session historical attempts, at least 30m apart.

    This policy never queries a provider and never promotes historical
    evidence to realtime. Its caller independently enforces the NY-local
    16:30 time, today's RTH source key and permitted market state.
    """
    if (
        type(attempts) is not int
        or not 0 <= attempts < 2
        or not isinstance(observed_at, datetime)
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
    ):
        return False
    if attempts == 0:
        return last_attempt_at is None
    if prior_status not in {"BLOCKED", "PARTIAL_HISTORICAL_ONLY"}:
        return False
    if (
        not isinstance(last_attempt_at, datetime)
        or last_attempt_at.tzinfo is None
        or last_attempt_at.utcoffset() is None
    ):
        return False
    # Refuse clock regressions, immediate burst retries, and a stale
    # previous-session attempt. Upstream also resets state at local midnight.
    elapsed = (observed_at - last_attempt_at).total_seconds()
    return 1800 <= elapsed <= 24 * 60 * 60


class ResearchMinuteCache(Protocol):
    def minute_bars(self, symbol: str) -> Sequence: ...
    def ingest(self, bar) -> bool: ...


HistoryPage = Callable[
    [str, str, str, object | None],
    tuple[Sequence[Mapping[str, object]], object | None],
]


def reconcile_us_postclose_terminal_minutes(
    symbols: Sequence[str],
    *,
    fetch_page: HistoryPage,
    market_data: ResearchMinuteCache,
    latest_time_keys: Mapping[str, str],
    observed_at: datetime,
    market_state: str,
) -> dict[str, object]:
    """Query at most one RTH historical page per symbol, once when caller gates.

    This is never a streaming close event, a currentness claim, a provider
    finality claim or a trading permission. Missing/partial grids do not
    repair themselves and must not be emitted as synthetic bars.
    """
    result: dict[str, object] = {
        "status": "BLOCKED",
        "reason": "NOT_QUALIFIED",
        "symbols": {},
        "provider_requests": 0,
        "seeded_count": 0,
        "historical_query": True,
        "currentness_proven": False,
        "bar_closure_promotion_authorized": False,
        "provider_finality": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "paper_auto_ready": False,
        "live_trade": False,
    }

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        return {**result, "reason": "OBSERVATION_CLOCK_INVALID"}
    if (
        not isinstance(symbols, (list, tuple))
        or not 1 <= len(symbols) <= MAX_SYMBOLS
        or any(
            not isinstance(symbol, str) or not symbol.startswith("US.")
            or not symbol[3:].replace(".", "").isalnum()
            or symbol != symbol.upper()
            for symbol in symbols
        )
        or len(set(symbols)) != len(symbols)
        or not isinstance(latest_time_keys, Mapping)
    ):
        return {**result, "reason": "SYMBOL_OR_PROVENANCE_INVALID"}

    local_now = observed_at.astimezone(EASTERN)
    day = local_now.date()
    result["session_date"] = day.isoformat()
    if local_now.time() < POSTCLOSE_BUFFER_END or str(market_state).upper() not in POSTCLOSE_MARKET_STATES:
        return {**result, "status": "NOT_DUE", "reason": "POSTCLOSE_WINDOW_NOT_QUALIFIED"}

    for symbol in symbols:
        item = {"status": "BLOCKED", "reason": "NO_QUALIFIED_RTH_TERMINAL_EVIDENCE"}
        result["symbols"][symbol] = item
        # A live RTH end label is an eligibility hint only, not finality.
        latest_key = latest_time_keys.get(symbol)
        if not isinstance(latest_key, str) or not latest_key.startswith(day.isoformat() + " "):
            continue
        try:
            label = datetime.strptime(latest_key, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if label.time() < time(15, 59):
            continue

        try:
            existing = tuple(market_data.minute_bars(symbol))
        except Exception as exc:
            item["reason"] = "CACHE_READ_EXCEPTION:" + type(exc).__name__
            continue
        # Never replace a live-complete 16:00 K1M; never query for a
        # completely unobserved session and fabricate its closing minute.
        final_start = datetime.combine(day, time(15, 59), tzinfo=EASTERN)
        final_end = final_start + timedelta(minutes=1)
        preterminal_start = final_start - timedelta(minutes=1)
        existing_terminal = [bar for bar in existing if bar.bar_start == final_start]
        if existing_terminal:
            if (
                len(existing_terminal) == 1
                and existing_terminal[0].bar_end == final_end
                and existing_terminal[0].provider == "futu"
                and existing_terminal[0].feed == "opend"
                and existing_terminal[0].session == "regular"
                and existing_terminal[0].is_closed is True
                and existing_terminal[0].is_complete is True
            ):
                item.update(status="ALREADY_PRESENT", reason="TERMINAL_MINUTE_ALREADY_IN_CACHE")
            else:
                item["reason"] = "EXISTING_TERMINAL_BAR_UNQUALIFIED"
            continue
        if not any(
            bar.symbol == symbol
            and bar.provider == "futu"
            and bar.feed == "opend"
            and bar.session == "regular"
            and bar.is_closed is True
            and bar.is_complete is True
            and bar.bar_start == preterminal_start
            and bar.bar_end == final_start
            for bar in existing
        ):
            item["reason"] = "MISSING_PRETERMINAL_LIVE_EVIDENCE"
            continue

        try:
            result["provider_requests"] += 1
            rows, next_page = fetch_page(symbol, day.isoformat(), day.isoformat(), None)
            if next_page is not None:
                item["reason"] = "HISTORY_PAGINATION_NOT_EXHAUSTED"
                continue
            normalized = normalize_futu_k1m_history_rows(
                rows,
                received_at=observed_at,
                expected_symbol=symbol,
                allow_completed_prior_session_tail=True,
            )
            if (
                normalized.closure_method != "QUALIFIED_POST_SESSION_FULL_GRID"
                or len(normalized.bars) != 390
            ):
                item["reason"] = "PROVIDER_FULL_GRID_NOT_QUALIFIED"
                continue
            last = normalized.bars[-1]
            if (
                last.bar_start != final_start
                or last.bar_end != final_end
                or last.is_closed is not True
                or last.is_complete is not True
                or last.session != "regular"
                or "HISTORICAL_QUERY" not in last.quality_flags
                or last.health.signal_permission.value == "normal"
            ):
                item["reason"] = "HISTORICAL_TERMINAL_BAR_INVALID"
                continue
            changed = market_data.ingest(last)
            if changed is not True:
                item["reason"] = "CACHE_INGEST_NOT_APPLIED"
                continue
            result["seeded_count"] += 1
            item.update(
                status="PASS_HISTORICAL_ONLY",
                reason="QUALIFIED_POST_SESSION_FULL_GRID",
                historical_time_key=day.isoformat() + " 16:00:00",
            )
        except Exception as exc:
            item["reason"] = "HISTORY_OR_CACHE_EXCEPTION:" + type(exc).__name__

    good = sum(
        item["status"] in {"PASS_HISTORICAL_ONLY", "ALREADY_PRESENT"}
        for item in result["symbols"].values()
    )
    result["status"] = (
        "ALREADY_PRESENT" if good == len(symbols) and result["seeded_count"] == 0
        else "PASS_HISTORICAL_ONLY" if good == len(symbols)
        else "PARTIAL_HISTORICAL_ONLY" if good else "BLOCKED"
    )
    result["reason"] = (
        "HISTORICAL_TERMINAL_RECONCILIATION"
        if good else "NO_QUALIFIED_TERMINAL_RECONCILIATION"
    )
    return result

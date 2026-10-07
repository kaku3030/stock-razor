from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Mapping, Protocol, Sequence

from .futu_k1m_history import FUTU_US_KLINE_TIMEZONE
from .futu_k1m_warm_start import build_futu_k1m_warm_start_selection


class MinuteBarIngestor(Protocol):
    def ingest(self, bar) -> bool: ...


HistoryPageFetcher = Callable[
    [str, str, str, object | None],
    tuple[Sequence[Mapping[str, object]], object | None],
]


@dataclass(frozen=True)
class FutuK1MSymbolWarmStartResult:
    status: str
    symbol: str
    session_date: str | None
    query_pages: int
    rows_seen: int
    planned_bar_count: int
    seeded_count: int
    unchanged_count: int
    closure_anchor_time_key: str | None
    reasons: tuple[str, ...] = ()
    session_dates: tuple[str, ...] = ()
    closure_anchor_time_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        payload["session_dates"] = list(self.session_dates)
        payload["closure_anchor_time_keys"] = list(self.closure_anchor_time_keys)
        return payload


@dataclass(frozen=True)
class FutuK1MRuntimeWarmStartResult:
    status: str
    symbols: tuple[FutuK1MSymbolWarmStartResult, ...]
    seeded_total: int
    unchanged_total: int
    lookback_days: int
    max_pages: int
    required_sessions: int
    purpose: str = field(default="RESEARCH_CACHE_WARM_START", init=False)
    historical_query: bool = field(default=True, init=False)
    realtime_currentness_proven: bool = field(default=False, init=False)
    bar_closure_promotion_authorized: bool = field(default=False, init=False)
    radar_admission: str = field(default="BLOCKED", init=False)
    live_trade: bool = field(default=False, init=False)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["symbols"] = {
            item.symbol: item.to_dict()
            for item in self.symbols
        }
        return payload


def seed_futu_k1m_research_cache(
    symbols: Sequence[str],
    *,
    fetch_page: HistoryPageFetcher,
    market_data: MinuteBarIngestor,
    received_at: datetime,
    lookback_days: int = 10,
    max_pages: int = 5,
    required_sessions: int = 3,
    session_end_date: date | None = None,
) -> FutuK1MRuntimeWarmStartResult:
    """Populate research cache from several closure-proven same-OpenD sessions.

    The fetcher is supplied by the runtime so this module remains provider-SDK
    free. Each symbol is isolated. A symbol seeds only when the full requested
    number of sessions qualifies; partial selections are never partially
    ingested.

    Historical facts never promote realtime currentness, live closure
    qualification, Radar admission, or execution.
    """

    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    if lookback_days < 2:
        raise ValueError("lookback_days must be at least 2")
    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    if required_sessions <= 0:
        raise ValueError("required_sessions must be positive")

    normalized_symbols = tuple(
        dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip())
    )
    if not normalized_symbols:
        raise ValueError("at least one symbol is required")
    if any(not symbol.startswith("US.") for symbol in normalized_symbols):
        raise ValueError("warm-start symbols must use canonical US.* form")

    effective_end = session_end_date or received_at.astimezone(
        FUTU_US_KLINE_TIMEZONE
    ).date()
    start_date = effective_end - timedelta(days=lookback_days)

    results: list[FutuK1MSymbolWarmStartResult] = []
    for symbol in normalized_symbols:
        rows: list[Mapping[str, object]] = []
        page_key: object | None = None
        pages = 0
        query_complete = False
        query_reason: str | None = None

        try:
            for _ in range(max_pages):
                page_rows, next_page_key = fetch_page(
                    symbol,
                    start_date.isoformat(),
                    effective_end.isoformat(),
                    page_key,
                )
                pages += 1
                rows.extend(dict(row) for row in page_rows)
                page_key = next_page_key
                if page_key is None:
                    query_complete = True
                    break
        except Exception as exc:
            query_reason = f"HISTORY_QUERY_EXCEPTION:{type(exc).__name__}"

        if query_reason is None and not query_complete:
            query_reason = "HISTORY_PAGE_LIMIT_EXCEEDED"

        if query_reason is not None:
            results.append(
                _blocked_symbol(
                    symbol,
                    pages=pages,
                    rows_seen=len(rows),
                    reasons=(query_reason,),
                )
            )
            continue

        try:
            selection = build_futu_k1m_warm_start_selection(
                rows,
                received_at=received_at,
                expected_symbol=symbol,
                requested_sessions=required_sessions,
            )
        except Exception as exc:
            results.append(
                _blocked_symbol(
                    symbol,
                    pages=pages,
                    rows_seen=len(rows),
                    reasons=(f"WARM_START_PLAN_EXCEPTION:{type(exc).__name__}",),
                )
            )
            continue

        if not selection.research_cache_seed_eligible:
            latest = selection.plans[0] if selection.plans else None
            results.append(
                FutuK1MSymbolWarmStartResult(
                    status="BLOCKED",
                    symbol=symbol,
                    session_date=latest.session_date if latest is not None else None,
                    query_pages=pages,
                    rows_seen=len(rows),
                    planned_bar_count=0,
                    seeded_count=0,
                    unchanged_count=0,
                    closure_anchor_time_key=(
                        latest.closure_anchor_time_key if latest is not None else None
                    ),
                    reasons=selection.reasons,
                    session_dates=selection.session_dates,
                    closure_anchor_time_keys=selection.closure_anchor_time_keys,
                )
            )
            continue

        ordered_plans = tuple(reversed(selection.plans))
        planned_bars = tuple(
            bar
            for plan in ordered_plans
            for bar in plan.bars
        )
        seeded = 0
        unchanged = 0
        try:
            for bar in planned_bars:
                if market_data.ingest(bar):
                    seeded += 1
                else:
                    unchanged += 1
        except Exception as exc:
            results.append(
                FutuK1MSymbolWarmStartResult(
                    status="BLOCKED",
                    symbol=symbol,
                    session_date=selection.plans[0].session_date,
                    query_pages=pages,
                    rows_seen=len(rows),
                    planned_bar_count=len(planned_bars),
                    seeded_count=seeded,
                    unchanged_count=unchanged,
                    closure_anchor_time_key=selection.plans[0].closure_anchor_time_key,
                    reasons=(f"CACHE_INGEST_EXCEPTION:{type(exc).__name__}",),
                    session_dates=selection.session_dates,
                    closure_anchor_time_keys=selection.closure_anchor_time_keys,
                )
            )
            continue

        results.append(
            FutuK1MSymbolWarmStartResult(
                status="PASS",
                symbol=symbol,
                session_date=selection.plans[0].session_date,
                query_pages=pages,
                rows_seen=len(rows),
                planned_bar_count=len(planned_bars),
                seeded_count=seeded,
                unchanged_count=unchanged,
                closure_anchor_time_key=selection.plans[0].closure_anchor_time_key,
                reasons=(),
                session_dates=selection.session_dates,
                closure_anchor_time_keys=selection.closure_anchor_time_keys,
            )
        )

    passed = sum(item.status == "PASS" for item in results)
    overall = "PASS" if passed == len(results) else ("PARTIAL" if passed else "BLOCKED")
    return FutuK1MRuntimeWarmStartResult(
        status=overall,
        symbols=tuple(results),
        seeded_total=sum(item.seeded_count for item in results),
        unchanged_total=sum(item.unchanged_count for item in results),
        lookback_days=lookback_days,
        max_pages=max_pages,
        required_sessions=required_sessions,
    )


def _blocked_symbol(
    symbol: str,
    *,
    pages: int,
    rows_seen: int,
    reasons: tuple[str, ...],
) -> FutuK1MSymbolWarmStartResult:
    return FutuK1MSymbolWarmStartResult(
        status="BLOCKED",
        symbol=symbol,
        session_date=None,
        query_pages=pages,
        rows_seen=rows_seen,
        planned_bar_count=0,
        seeded_count=0,
        unchanged_count=0,
        closure_anchor_time_key=None,
        reasons=reasons,
    )

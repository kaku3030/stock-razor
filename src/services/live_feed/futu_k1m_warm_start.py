from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Mapping, Sequence

from data_provider.market_data_adapter import Bar
from .futu_k1m_history import normalize_futu_k1m_history_rows
from .futu_k1m_history_qualification import qualify_futu_us_k1m_history


@dataclass(frozen=True)
class FutuK1MWarmStartPlan:
    """One closure-proven research-cache seed session."""

    status: str
    symbol: str
    session_date: str | None
    bars: tuple[Bar, ...]
    closure_anchor_time_key: str | None
    rows_seen: int
    reasons: tuple[str, ...] = ()
    purpose: str = field(default="RESEARCH_CACHE_WARM_START", init=False)
    historical_query: bool = field(default=True, init=False)
    realtime_currentness_proven: bool = field(default=False, init=False)
    bar_closure_promotion_authorized: bool = field(default=False, init=False)
    radar_admission: str = field(default="BLOCKED", init=False)
    live_trade: bool = field(default=False, init=False)

    @property
    def research_cache_seed_eligible(self) -> bool:
        return self.status == "PASS" and bool(self.bars)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload.pop("bars", None)
        payload["bar_count"] = len(self.bars)
        payload["research_cache_seed_eligible"] = self.research_cache_seed_eligible
        payload["reasons"] = list(self.reasons)
        return payload


@dataclass(frozen=True)
class FutuK1MWarmStartSelection:
    """Bounded newest-first set of closure-proven research sessions."""

    status: str
    symbol: str
    plans: tuple[FutuK1MWarmStartPlan, ...]
    requested_sessions: int
    rows_seen: int
    reasons: tuple[str, ...] = ()
    purpose: str = field(default="RESEARCH_CACHE_WARM_START", init=False)
    historical_query: bool = field(default=True, init=False)
    realtime_currentness_proven: bool = field(default=False, init=False)
    bar_closure_promotion_authorized: bool = field(default=False, init=False)
    radar_admission: str = field(default="BLOCKED", init=False)
    live_trade: bool = field(default=False, init=False)

    @property
    def research_cache_seed_eligible(self) -> bool:
        return (
            self.status == "PASS"
            and len(self.plans) == self.requested_sessions
            and all(plan.research_cache_seed_eligible for plan in self.plans)
        )

    @property
    def bar_count(self) -> int:
        return sum(len(plan.bars) for plan in self.plans)

    @property
    def session_dates(self) -> tuple[str, ...]:
        return tuple(
            plan.session_date
            for plan in reversed(self.plans)
            if plan.session_date is not None
        )

    @property
    def closure_anchor_time_keys(self) -> tuple[str, ...]:
        return tuple(
            plan.closure_anchor_time_key
            for plan in reversed(self.plans)
            if plan.closure_anchor_time_key is not None
        )

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "requested_sessions": self.requested_sessions,
            "selected_sessions": len(self.plans),
            "session_dates": list(self.session_dates),
            "closure_anchor_time_keys": list(self.closure_anchor_time_keys),
            "rows_seen": self.rows_seen,
            "bar_count": self.bar_count,
            "research_cache_seed_eligible": self.research_cache_seed_eligible,
            "reasons": list(self.reasons),
            "purpose": self.purpose,
            "historical_query": self.historical_query,
            "realtime_currentness_proven": self.realtime_currentness_proven,
            "bar_closure_promotion_authorized": self.bar_closure_promotion_authorized,
            "radar_admission": self.radar_admission,
            "live_trade": self.live_trade,
        }


def build_futu_k1m_warm_start_selection(
    rows: Sequence[Mapping[str, object]],
    *,
    received_at: datetime,
    expected_symbol: str,
    requested_sessions: int = 3,
) -> FutuK1MWarmStartSelection:
    """Select newest complete sessions that each have next-label closure proof.

    Plans are stored newest-first. Consumers that ingest several plans should
    reverse the tuple and ingest oldest-to-newest. Historical qualification
    never proves realtime currentness or authorizes Radar/trading.
    """

    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("received_at must be timezone-aware")
    if requested_sessions <= 0:
        raise ValueError("requested_sessions must be positive")

    symbol = str(expected_symbol or "").strip().upper()
    if not symbol.startswith("US."):
        raise ValueError("expected_symbol must use canonical US.* form")

    materialized = [dict(row) for row in rows]
    if not materialized:
        return _selection_blocked(
            symbol,
            requested_sessions=requested_sessions,
            rows_seen=0,
            reasons=("NO_ROWS",),
        )

    parsed: list[tuple[datetime, dict[str, object]]] = []
    for row in materialized:
        row_symbol = str(row.get("code") or "").strip().upper()
        if row_symbol != symbol:
            return _selection_blocked(
                symbol,
                requested_sessions=requested_sessions,
                rows_seen=len(materialized),
                reasons=("SYMBOL_MISMATCH",),
            )
        raw_time = str(row.get("time_key") or "").strip()
        try:
            stamp = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return _selection_blocked(
                symbol,
                requested_sessions=requested_sessions,
                rows_seen=len(materialized),
                reasons=("TIME_KEY_PARSE_ERROR",),
            )
        parsed.append((stamp, row))

    stamps = [stamp for stamp, _ in parsed]
    if stamps != sorted(stamps) or len(stamps) != len(set(stamps)):
        return _selection_blocked(
            symbol,
            requested_sessions=requested_sessions,
            rows_seen=len(materialized),
            reasons=("QUERY_TIME_KEY_NOT_STRICTLY_INCREASING",),
        )

    by_date: dict[date, list[dict[str, object]]] = {}
    time_key_indexes: dict[str, int] = {}
    for index, (stamp, row) in enumerate(parsed):
        by_date.setdefault(stamp.date(), []).append(row)
        time_key_indexes[str(row.get("time_key") or "").strip()] = index

    plans: list[FutuK1MWarmStartPlan] = []
    deferred_reasons: list[str] = []
    for session_date in sorted(by_date, reverse=True):
        session_rows = by_date[session_date]
        qualification = qualify_futu_us_k1m_history(
            session_rows,
            expected_symbol=symbol,
            expected_session_date=session_date,
        )
        if not qualification.research_cache_seed_eligible:
            deferred_reasons.extend(
                f"{session_date.isoformat()}:{reason}"
                for reason in qualification.reasons
            )
            continue

        last_time_key = qualification.last_time_key
        last_index = time_key_indexes.get(str(last_time_key or ""))
        if last_index is None or last_index + 1 >= len(parsed):
            deferred_reasons.append(
                f"{session_date.isoformat()}:MISSING_LATER_PROVIDER_LABEL"
            )
            continue

        anchor_row = parsed[last_index + 1][1]
        anchor_time_key = str(anchor_row.get("time_key") or "").strip()
        normalization = normalize_futu_k1m_history_rows(
            [*session_rows, anchor_row],
            received_at=received_at,
            expected_symbol=symbol,
        )
        if len(normalization.bars) != qualification.expected_row_count:
            deferred_reasons.append(
                f"{session_date.isoformat()}:NORMALIZED_BAR_COUNT_MISMATCH"
            )
            continue
        if normalization.unresolved_tail is None:
            deferred_reasons.append(
                f"{session_date.isoformat()}:CLOSURE_ANCHOR_NOT_RETAINED_AS_TAIL"
            )
            continue
        if normalization.unresolved_tail.time_key != anchor_time_key:
            deferred_reasons.append(
                f"{session_date.isoformat()}:CLOSURE_ANCHOR_MISMATCH"
            )
            continue

        plans.append(
            FutuK1MWarmStartPlan(
                status="PASS",
                symbol=symbol,
                session_date=session_date.isoformat(),
                bars=normalization.bars,
                closure_anchor_time_key=anchor_time_key,
                rows_seen=len(materialized),
                reasons=(),
            )
        )
        if len(plans) == requested_sessions:
            break

    if len(plans) == requested_sessions:
        return FutuK1MWarmStartSelection(
            status="PASS",
            symbol=symbol,
            plans=tuple(plans),
            requested_sessions=requested_sessions,
            rows_seen=len(materialized),
            reasons=(),
        )

    shortage = (
        f"INSUFFICIENT_CLOSURE_PROVEN_SESSIONS:{len(plans)}/{requested_sessions}"
    )
    reasons = tuple(
        dict.fromkeys(
            [shortage, *deferred_reasons]
            if deferred_reasons
            else [shortage, "NO_QUALIFIED_CLOSURE_PROVEN_SESSION"]
        )
    )
    return FutuK1MWarmStartSelection(
        status="PARTIAL" if plans else "BLOCKED",
        symbol=symbol,
        plans=tuple(plans),
        requested_sessions=requested_sessions,
        rows_seen=len(materialized),
        reasons=reasons,
    )


def build_futu_k1m_warm_start_plan(
    rows: Sequence[Mapping[str, object]],
    *,
    received_at: datetime,
    expected_symbol: str,
) -> FutuK1MWarmStartPlan:
    """Backward-compatible newest single-session warm-start plan."""

    selection = build_futu_k1m_warm_start_selection(
        rows,
        received_at=received_at,
        expected_symbol=expected_symbol,
        requested_sessions=1,
    )
    if selection.research_cache_seed_eligible:
        return selection.plans[0]
    return _blocked(
        selection.symbol,
        rows_seen=selection.rows_seen,
        reasons=selection.reasons,
    )


def _selection_blocked(
    symbol: str,
    *,
    requested_sessions: int,
    rows_seen: int,
    reasons: tuple[str, ...],
) -> FutuK1MWarmStartSelection:
    return FutuK1MWarmStartSelection(
        status="BLOCKED",
        symbol=symbol,
        plans=(),
        requested_sessions=requested_sessions,
        rows_seen=rows_seen,
        reasons=reasons,
    )


def _blocked(
    symbol: str,
    *,
    rows_seen: int,
    reasons: tuple[str, ...],
) -> FutuK1MWarmStartPlan:
    return FutuK1MWarmStartPlan(
        status="BLOCKED",
        symbol=symbol,
        session_date=None,
        bars=(),
        closure_anchor_time_key=None,
        rows_seen=rows_seen,
        reasons=reasons,
    )

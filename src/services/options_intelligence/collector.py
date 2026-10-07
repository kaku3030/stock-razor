"""Pure qualification core for US options-intelligence collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from .contract import OptionsIntelligencePacket, build_options_intelligence_packet
from .futu_snapshot_adapter import normalize_futu_snapshot_rows
from .gamma_profile import apply_gamma_profile, build_gamma_profile
from .gex import build_gex_evidence
from .qualification import (
    OptionsClockQualification,
    OptionsFreshnessPolicy,
    qualify_options_clock_alignment,
    qualify_quote_freshness_with_policy,
    resolve_us_options_freshness_policy,
)


ET = ZoneInfo("America/New_York")
_XNYS = xcals.get_calendar("XNYS")


@dataclass(frozen=True)
class UsOptionsSessionContext:
    phase: str
    evaluated_at: datetime
    session_date: object
    session_open: datetime | None
    session_close: datetime | None
    reference_session_close: datetime | None
    status: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CollectorSymbolResult:
    symbol: str
    status: str
    phase: str
    packet: OptionsIntelligencePacket | None
    policy: OptionsFreshnessPolicy | None
    clock: OptionsClockQualification | None
    source_contracts_total: int
    normalized_contracts: int
    fresh_contracts: int
    reasons: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return self.packet is not None


def _as_market_datetime(value: object) -> datetime:
    if hasattr(value, "tz_convert"):
        return value.tz_convert("America/New_York").to_pydatetime()
    if isinstance(value, datetime):
        return value.astimezone(ET) if value.tzinfo is not None else value.replace(tzinfo=ET)
    if hasattr(value, "to_pydatetime"):
        converted = value.to_pydatetime()
        return converted.astimezone(ET) if converted.tzinfo is not None else converted.replace(tzinfo=ET)
    raise ValueError("calendar timestamp cannot be converted")


def resolve_us_options_session_context(
    evaluated_at: datetime,
) -> UsOptionsSessionContext:
    """Resolve phase and completed-session close using XNYS calendar semantics."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    local = evaluated_at.astimezone(ET)
    local_date = local.date()

    try:
        if not _XNYS.is_session(local_date):
            previous = _XNYS.date_to_session(local_date, direction="previous")
            previous_close = _as_market_datetime(_XNYS.session_close(previous))
            return UsOptionsSessionContext(
                phase="non_trading",
                evaluated_at=local,
                session_date=local_date,
                session_open=None,
                session_close=None,
                reference_session_close=previous_close,
                status="BLOCKED_UNSUPPORTED_PHASE",
                warnings=("NON_TRADING_OPTIONS_COLLECTION_BLOCKED",),
            )

        session = _XNYS.date_to_session(local_date, direction="previous")
        session_open = _as_market_datetime(_XNYS.session_open(session))
        session_close = _as_market_datetime(_XNYS.session_close(session))

        if local < session_open:
            previous = _XNYS.previous_session(session)
            previous_close = _as_market_datetime(_XNYS.session_close(previous))
            return UsOptionsSessionContext(
                phase="premarket",
                evaluated_at=local,
                session_date=local_date,
                session_open=session_open,
                session_close=session_close,
                reference_session_close=previous_close,
                status="READY",
            )

        if local < session_close:
            return UsOptionsSessionContext(
                phase="intraday",
                evaluated_at=local,
                session_date=local_date,
                session_open=session_open,
                session_close=session_close,
                reference_session_close=None,
                status="READY",
            )

        return UsOptionsSessionContext(
            phase="postmarket",
            evaluated_at=local,
            session_date=local_date,
            session_open=session_open,
            session_close=session_close,
            reference_session_close=session_close,
            status="BLOCKED_UNSUPPORTED_PHASE",
            warnings=("POSTMARKET_SPOT_SEMANTICS_NOT_QUALIFIED",),
        )
    except Exception as exc:
        return UsOptionsSessionContext(
            phase="unknown",
            evaluated_at=local,
            session_date=local_date,
            session_open=None,
            session_close=None,
            reference_session_close=None,
            status="BLOCKED_CALENDAR_ERROR",
            warnings=(f"CALENDAR_ERROR:{type(exc).__name__}",),
        )


def _finite_float(row: Mapping[str, object], field: str) -> float:
    try:
        value = float(row.get(field))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is missing or non-numeric") from exc
    if not isfinite(value):
        raise ValueError(f"{field} must be finite")
    return value


def _parse_futu_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("underlying update_time is required")
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=ET)
    return parsed.astimezone(ET)


def _select_spot(
    underlying_row: Mapping[str, object],
    session: UsOptionsSessionContext,
) -> tuple[float, datetime, str]:
    if session.phase == "premarket":
        if session.reference_session_close is None:
            raise ValueError("premarket reference session close is required")
        spot = _finite_float(underlying_row, "prev_close_price")
        if spot <= 0:
            raise ValueError("prev_close_price must be positive")
        return spot, session.reference_session_close, "previous_regular_close"

    if session.phase == "intraday":
        spot = _finite_float(underlying_row, "last_price")
        if spot <= 0:
            raise ValueError("last_price must be positive")
        return spot, _parse_futu_time(underlying_row.get("update_time")), "regular_last"

    raise ValueError(f"unsupported options collection phase: {session.phase}")


def build_futu_options_intelligence_packet(
    *,
    symbol: str,
    underlying_row: Mapping[str, object],
    option_rows: Iterable[Mapping[str, object]],
    evaluated_at: datetime,
) -> CollectorSymbolResult:
    """Build a qualified packet from already-fetched Futu rows.

    Provider I/O is intentionally outside this function.
    """

    canonical_symbol = str(symbol or "").strip().upper()
    if canonical_symbol.startswith("US."):
        underlying_symbol = canonical_symbol[3:]
    else:
        underlying_symbol = canonical_symbol
        canonical_symbol = f"US.{canonical_symbol}"
    if not underlying_symbol:
        raise ValueError("symbol is required")

    session = resolve_us_options_session_context(evaluated_at)
    raw_options = list(option_rows)
    if session.status != "READY":
        return CollectorSymbolResult(
            symbol=canonical_symbol,
            status="BLOCKED",
            phase=session.phase,
            packet=None,
            policy=None,
            clock=None,
            source_contracts_total=len(raw_options),
            normalized_contracts=0,
            fresh_contracts=0,
            reasons=session.warnings or (session.status,),
        )

    try:
        spot, spot_asof, spot_source = _select_spot(underlying_row, session)
    except ValueError as exc:
        return CollectorSymbolResult(
            symbol=canonical_symbol,
            status="BLOCKED",
            phase=session.phase,
            packet=None,
            policy=None,
            clock=None,
            source_contracts_total=len(raw_options),
            normalized_contracts=0,
            fresh_contracts=0,
            reasons=(f"SPOT_SELECTION_FAILED:{exc}",),
        )

    normalized = normalize_futu_snapshot_rows(
        raw_options,
        underlying_symbol=underlying_symbol,
        oi_asof=None,
    )
    policy = resolve_us_options_freshness_policy(
        evaluated_at=session.evaluated_at,
        phase=session.phase,
        reference_session_close=session.reference_session_close,
    )
    freshness = qualify_quote_freshness_with_policy(
        normalized.observations,
        policy=policy,
    )
    clock = qualify_options_clock_alignment(
        freshness,
        underlying_asof=spot_asof,
    )

    if not freshness.observations:
        return CollectorSymbolResult(
            symbol=canonical_symbol,
            status="BLOCKED",
            phase=session.phase,
            packet=None,
            policy=policy,
            clock=clock,
            source_contracts_total=normalized.total_rows,
            normalized_contracts=normalized.usable_rows,
            fresh_contracts=0,
            reasons=("NO_FRESH_OPTION_OBSERVATIONS",),
        )

    current = build_gex_evidence(
        freshness.observations,
        spot=spot,
        market_date=session.session_date,
        calculated_at=session.evaluated_at,
        source_contracts_total=normalized.total_rows,
        spot_asof=spot_asof,
        spot_source=spot_source,
    )
    profile = build_gamma_profile(
        freshness.observations,
        reference_spot=spot,
        calculated_at=session.evaluated_at,
        source_contracts_total=normalized.total_rows,
    )
    current = apply_gamma_profile(current, profile)
    packet = build_options_intelligence_packet(
        current_gex=current,
        freshness=freshness,
        gamma_profile=profile,
        generated_at=session.evaluated_at,
        clock_alignment=clock,
    )

    return CollectorSymbolResult(
        symbol=canonical_symbol,
        status=packet.context_permission,
        phase=session.phase,
        packet=packet,
        policy=policy,
        clock=clock,
        source_contracts_total=normalized.total_rows,
        normalized_contracts=normalized.usable_rows,
        fresh_contracts=freshness.usable,
    )

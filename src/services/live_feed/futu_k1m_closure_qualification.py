from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from data_provider.market_data_adapter import Bar

from .futu_k1m_currentness import FutuK1MCurrentnessResult


@dataclass(frozen=True)
class FutuK1MClosureQualificationResult:
    symbol: str
    status: str
    reason: str
    consecutive_boundaries: int
    required_consecutive_boundaries: int
    interval_start_utc: datetime | None = None
    interval_end_utc: datetime | None = None
    latest_closed_bar_start_utc: datetime | None = None
    latest_closed_bar_end_utc: datetime | None = None
    latest_closed_bar_source_timestamp_utc: datetime | None = None
    boundary_delta_seconds: float | None = None
    evidence_scope: str = "RUNTIME_REGULAR_SESSION"
    bar_closure: str = "UNPROVEN"
    delivery_mode: str = "UNKNOWN"
    radar_admission: str = "BLOCKED"
    live_trade: bool = False

    @property
    def can_promote(self) -> bool:
        return False


@dataclass
class _SymbolState:
    last_boundary_utc: datetime | None = None
    consecutive_boundaries: int = 0


class FutuK1MClosureQualificationTracker:
    """Accumulate runtime evidence for Futu K_1M closure semantics.

    This proves only the relation between a provider forming interval-END
    label and the latest canonical closed 1m bar. It does not promote
    bar_closure, DeliveryMode, Radar admission, or trading.
    """

    def __init__(self, *, required_consecutive_boundaries: int = 3) -> None:
        if required_consecutive_boundaries < 2:
            raise ValueError("required_consecutive_boundaries must be at least 2")
        self._required = required_consecutive_boundaries
        self._states: dict[str, _SymbolState] = {}

    def observe(
        self,
        symbol: str,
        *,
        currentness: FutuK1MCurrentnessResult,
        latest_closed_bar: Bar | None,
    ) -> FutuK1MClosureQualificationResult:
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol is required")
        state = self._states.setdefault(normalized_symbol, _SymbolState())

        if currentness.status == "NOT_APPLICABLE":
            self._reset(state)
            return self._result(
                normalized_symbol, currentness=currentness,
                latest_closed_bar=latest_closed_bar,
                status="NOT_APPLICABLE", reason="CURRENTNESS_NOT_APPLICABLE",
                state=state,
            )
        if currentness.status == "FAIL":
            self._reset(state)
            return self._result(
                normalized_symbol, currentness=currentness,
                latest_closed_bar=latest_closed_bar,
                status="FAIL",
                reason=f"CURRENTNESS_FAIL:{currentness.reason}",
                state=state,
            )
        if currentness.status != "PASS":
            self._reset(state)
            return self._result(
                normalized_symbol, currentness=currentness,
                latest_closed_bar=latest_closed_bar,
                status="UNKNOWN",
                reason=f"CURRENTNESS_{currentness.status or 'UNKNOWN'}",
                state=state,
            )

        interval_start = currentness.interval_start_utc
        interval_end = currentness.interval_end_utc
        if interval_start is None or interval_end is None:
            self._reset(state)
            return self._result(
                normalized_symbol, currentness=currentness,
                latest_closed_bar=latest_closed_bar,
                status="FAIL",
                reason="PASS_CURRENTNESS_MISSING_INTERVAL_BOUNDARIES",
                state=state,
            )
        interval_start = self._utc(interval_start)
        interval_end = self._utc(interval_end)
        if interval_end - interval_start != timedelta(minutes=1):
            self._reset(state)
            return self._result(
                normalized_symbol, currentness=currentness,
                latest_closed_bar=latest_closed_bar,
                status="FAIL", reason="INVALID_PROVIDER_INTERVAL_WIDTH",
                state=state,
            )
        if latest_closed_bar is None:
            return self._result(
                normalized_symbol, currentness=currentness,
                latest_closed_bar=None, status="UNKNOWN",
                reason="WAITING_FOR_FIRST_CANONICAL_CLOSED_BAR",
                state=state,
            )

        mismatch_reason = self._bar_mismatch_reason(
            normalized_symbol, interval_start=interval_start,
            bar=latest_closed_bar,
        )
        if mismatch_reason is not None:
            self._reset(state)
            return self._result(
                normalized_symbol, currentness=currentness,
                latest_closed_bar=latest_closed_bar,
                status="FAIL", reason=mismatch_reason, state=state,
            )

        boundary = interval_start
        if state.last_boundary_utc is None:
            state.last_boundary_utc = boundary
            state.consecutive_boundaries = 1
        elif boundary == state.last_boundary_utc:
            pass
        elif boundary == state.last_boundary_utc + timedelta(minutes=1):
            state.last_boundary_utc = boundary
            state.consecutive_boundaries += 1
        elif boundary > state.last_boundary_utc:
            state.last_boundary_utc = boundary
            state.consecutive_boundaries = 1
            return self._result(
                normalized_symbol, currentness=currentness,
                latest_closed_bar=latest_closed_bar,
                status="UNKNOWN", reason="BOUNDARY_GAP_RESET",
                state=state,
            )
        else:
            self._reset(state)
            return self._result(
                normalized_symbol, currentness=currentness,
                latest_closed_bar=latest_closed_bar,
                status="FAIL", reason="BOUNDARY_REGRESSION",
                state=state,
            )

        if state.consecutive_boundaries >= self._required:
            status = "PASS"
            reason = "CONSECUTIVE_CLOSURE_BOUNDARIES_PROVEN"
        else:
            status = "UNKNOWN"
            reason = "WAITING_FOR_CONSECUTIVE_CLOSURE_EVIDENCE"
        return self._result(
            normalized_symbol, currentness=currentness,
            latest_closed_bar=latest_closed_bar,
            status=status, reason=reason, state=state,
        )

    @staticmethod
    def _reset(state: _SymbolState) -> None:
        state.last_boundary_utc = None
        state.consecutive_boundaries = 0

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("closure qualification timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    def _bar_mismatch_reason(
        self, symbol: str, *, interval_start: datetime, bar: Bar
    ) -> str | None:
        if bar.symbol.upper() != symbol:
            return "CANONICAL_SYMBOL_MISMATCH"
        if bar.timeframe != "1m":
            return "CANONICAL_TIMEFRAME_MISMATCH"
        if bar.provider != "futu":
            return "CANONICAL_PROVIDER_MISMATCH"
        if bar.feed != "opend":
            return "CANONICAL_FEED_MISMATCH"
        if not bar.is_closed:
            return "CANONICAL_BAR_NOT_CLOSED"
        if not bar.is_complete:
            return "CANONICAL_BAR_NOT_COMPLETE"
        bar_start = self._utc(bar.bar_start)
        bar_end = self._utc(bar.bar_end)
        source_timestamp = self._utc(bar.source_timestamp)
        if bar_end - bar_start != timedelta(minutes=1):
            return "CANONICAL_INTERVAL_WIDTH_MISMATCH"
        if source_timestamp != bar_end:
            return "CANONICAL_SOURCE_TIMESTAMP_MISMATCH"
        if bar_end != interval_start:
            return "FORMING_START_DOES_NOT_MATCH_LATEST_CLOSED_END"
        return None

    def _result(
        self,
        symbol: str,
        *,
        currentness: FutuK1MCurrentnessResult,
        latest_closed_bar: Bar | None,
        status: str,
        reason: str,
        state: _SymbolState,
    ) -> FutuK1MClosureQualificationResult:
        interval_start = currentness.interval_start_utc
        interval_end = currentness.interval_end_utc
        bar_start = latest_closed_bar.bar_start if latest_closed_bar else None
        bar_end = latest_closed_bar.bar_end if latest_closed_bar else None
        source_timestamp = latest_closed_bar.source_timestamp if latest_closed_bar else None
        delta = None
        if interval_start is not None and bar_end is not None:
            delta = (self._utc(bar_end) - self._utc(interval_start)).total_seconds()
        return FutuK1MClosureQualificationResult(
            symbol=symbol, status=status, reason=reason,
            consecutive_boundaries=state.consecutive_boundaries,
            required_consecutive_boundaries=self._required,
            interval_start_utc=(self._utc(interval_start) if interval_start is not None else None),
            interval_end_utc=(self._utc(interval_end) if interval_end is not None else None),
            latest_closed_bar_start_utc=(self._utc(bar_start) if bar_start is not None else None),
            latest_closed_bar_end_utc=(self._utc(bar_end) if bar_end is not None else None),
            latest_closed_bar_source_timestamp_utc=(
                self._utc(source_timestamp) if source_timestamp is not None else None
            ),
            boundary_delta_seconds=delta,
        )


def summarize_futu_k1m_closure_qualification(
    results: dict[str, FutuK1MClosureQualificationResult],
) -> str:
    if not results:
        return "UNKNOWN"
    statuses = [item.status for item in results.values()]
    if any(status == "FAIL" for status in statuses):
        return "FAIL"
    if all(status == "PASS" for status in statuses):
        return "PASS"
    if all(status == "NOT_APPLICABLE" for status in statuses):
        return "NOT_APPLICABLE"
    return "UNKNOWN"
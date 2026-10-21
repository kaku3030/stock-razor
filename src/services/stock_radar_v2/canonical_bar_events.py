"""Canonical OpenD closed-bar facts into the existing durable research inbox.

This adapter performs no provider requests, AI calls, sends or admission changes.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from typing import TYPE_CHECKING

from data_provider.market_data_adapter import Bar, MarketDataHealth, SignalPermission
from src.core.trading_calendar import MarketPhase, infer_market_phase
from src.services.live_feed.futu_k1m_currentness import REGULAR_MARKET_STATES
from src.services.live_feed.us_intraday_closure import (
    US_EASTERN, qualify_us_current_session_intraday_closure,
)
from src.services.stock_radar_v2.bar_event_ledger import (
    ClosedBarEventCandidate, EventQueueFull, RadarBarEventLedger,
)

if TYPE_CHECKING:
    from src.services.stock_radar_v2.canonical_snapshot_worker import CanonicalSnapshotSource


@dataclass(frozen=True)
class CanonicalBarEventIngressResult:
    status: str
    created_count: int = 0
    duplicate_count: int = 0
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {**asdict(self), "reasons": list(self.reasons)}


def _normal(health: MarketDataHealth | None) -> bool:
    return bool(health is not None and health.signal_permission is SignalPermission.NORMAL
                and health.score >= 80 and not health.quality_flags)


# These flags describe a bar that is useful for observation but unsafe for a
# closed-bar event. They quarantine only the affected symbol/timeframe; they
# must not suppress valid events for the rest of the candidate set.
_SYMBOL_BAR_QUARANTINE_FLAGS = frozenset({
    "VWAP_OUTSIDE_BAR_RANGE",
    "PARTIAL_TURNOVER",
})


def _is_symbol_bar_quarantinable(bar: Bar) -> bool:
    flags = {
        str(flag).strip().upper()
        for flag in bar.quality_flags
        if str(flag).strip()
    }
    return bool(flags) and flags.issubset(_SYMBOL_BAR_QUARANTINE_FLAGS)

def _is_symbol_health_quarantinable(health: MarketDataHealth | None) -> bool:
    if health is None:
        return False
    flags = {
        str(flag).strip().upper()
        for flag in health.quality_flags
        if str(flag).strip()
    }
    return bool(flags) and flags.issubset(_SYMBOL_BAR_QUARANTINE_FLAGS)


def _quarantine_flags(values: object) -> str:
    flags = {
        str(flag).strip().upper()
        for flag in values
        if str(flag).strip()
    }
    return ",".join(sorted(flags))


def _qualified_bar(bar: Bar, *, observed_at: datetime, minutes: int) -> bool:
    local_start = bar.bar_start.astimezone(US_EASTERN)
    local_end = bar.bar_end.astimezone(US_EASTERN)
    session_start = datetime.combine(local_start.date(), time(9, 30), US_EASTERN)
    session_end = datetime.combine(local_start.date(), time(16), US_EASTERN)
    return bool(
        bar.provider == "futu" and bar.feed == "opend" and bar.market == "us"
        and bar.session == "regular" and not bar.fallback_from and not bar.fallback_reason
        and bar.is_closed and bar.is_complete and not bar.quality_flags and _normal(bar.health)
        and session_start <= local_start < local_end <= session_end
        and local_start.date() == observed_at.astimezone(US_EASTERN).date()
        and (local_start - session_start).total_seconds() % (minutes * 60) == 0
        and local_end == min(local_start + timedelta(minutes=minutes), session_end)
        and bar.source_timestamp == bar.bar_end
        and bar.bar_end <= bar.received_at <= observed_at
        and bar.amount is not None and bar.amount >= 0 and bar.volume >= 0
        and ((bar.volume == 0 and bar.amount == 0) or
             (bar.volume > 0 and bar.low - max(1e-6, abs(bar.low) * 1e-6)
              <= bar.amount / bar.volume <= bar.high + max(1e-6, abs(bar.high) * 1e-6)))
    )


def record_canonical_closed_bars(
    source: CanonicalSnapshotSource, ledger: RadarBarEventLedger, *,
    observed_at: datetime, max_age_seconds: int,
) -> CanonicalBarEventIngressResult:
    """Validate the complete candidate set before the first per-bar transaction.

    Caller enforces exact source SHA and source sequence before this function.
    Partial storage success is durable: on failure the caller must NOT advance
    its successful source watermark; replay dedupes committed bars and retries
    remaining ones. No catch-up events are created from old higher-timeframe bars.
    """
    def blocked(reason: str, created: int = 0, duplicates: int = 0):
        return CanonicalBarEventIngressResult("BLOCKED", created, duplicates, (reason,))

    if source.delivery_mode != "REALTIME" or source.bar_closure != "PROVEN":
        return blocked("BAR_EVENT_SOURCE_NOT_QUALIFIED")
    if (source.market_state_us.strip().upper() not in REGULAR_MARKET_STATES
            or source.cache_session_us != "regular"
            or infer_market_phase("us", observed_at) not in {
                MarketPhase.INTRADAY, MarketPhase.CLOSING_AUCTION}):
        return blocked("BAR_EVENT_SESSION_NOT_CONFIRMED")
    if not 0 <= (observed_at - source.emitted_at).total_seconds() <= max_age_seconds:
        return blocked("BAR_EVENT_SOURCE_TIME_INVALID")

    candidates = []
    quarantined: list[str] = []
    for snapshot in source.snapshots:
        if (not snapshot.symbol.startswith("US.") or snapshot.provider != "futu"
                or snapshot.feed != "opend" or snapshot.fallback_from or snapshot.fallback_reason
                or not snapshot.minute_bars
                or not 0 <= (observed_at - snapshot.as_of).total_seconds() <= max_age_seconds
                or snapshot.as_of > source.emitted_at):
            return blocked("BAR_EVENT_SNAPSHOT_NOT_QUALIFIED")
        if not _normal(snapshot.health):
            if _is_symbol_health_quarantinable(snapshot.health):
                quarantined.append(
                    f"SYMBOL_HEALTH_QUARANTINED:{snapshot.symbol}:"
                    f"{_quarantine_flags(snapshot.health.quality_flags)}"
                )
            else:
                return blocked("BAR_EVENT_SNAPSHOT_NOT_QUALIFIED")
        latest = snapshot.minute_bars[-1]
        if (not _qualified_bar(latest, observed_at=observed_at, minutes=1)
                or not 0 <= (observed_at - latest.bar_end).total_seconds() <= max_age_seconds):
            return blocked("BAR_EVENT_MINUTE_NOT_CURRENT")
        frames = {"15m": list(snapshot.bars_15m), "1h": list(snapshot.bars_1h)}
        closure = qualify_us_current_session_intraday_closure(frames, as_of=observed_at)
        if closure["status"] != "PASS":
            return blocked("BAR_EVENT_CLOSED_GRID_NOT_PROVEN")
        for timeframe, minutes in (("15m", 15), ("1h", 60)):
            closed = [bar for bar in frames[timeframe]
                      if bar.is_closed and bar.is_complete and bar.bar_end <= observed_at]
            bar = max(closed, key=lambda item: item.bar_end)
            if (observed_at - bar.bar_end).total_seconds() > max_age_seconds:
                continue
            if not _qualified_bar(bar, observed_at=observed_at, minutes=minutes):
                if _is_symbol_bar_quarantinable(bar):
                    flags = _quarantine_flags(bar.quality_flags)
                    quarantined.append(
                        f"SYMBOL_BAR_QUARANTINED:{snapshot.symbol}:{timeframe}:{flags}"
                    )
                    continue
                return blocked("BAR_EVENT_BAR_NOT_QUALIFIED")
            try:
                candidates.append(ClosedBarEventCandidate(
                    provider_id="futu", symbol=bar.symbol, timeframe=timeframe,
                    bar_end=bar.bar_end, observed_at=observed_at,
                    exchange_timezone="America/New_York",
                    session_id=bar.bar_end.astimezone(US_EASTERN).date().isoformat(),
                    session_status="CONFIRMED", freshness_status="FRESH",
                    quality_status="PASS", quality_flags=(),
                    open=bar.open, high=bar.high, low=bar.low, close=bar.close,
                    volume=bar.volume, turnover=bar.amount,
                    source_revision=source.repo_sha, source_runtime_id=source.runtime_instance_id,
                    source_sequence=source.sequence, rule_id="canonical_closed_bar",
                    rule_revision="1", signal_kind="closed_bar_observation",
                    evidence={"bar_start_utc": bar.bar_start.isoformat(),
                              "provider_feed": "opend", "delivery_mode": "REALTIME",
                              "bar_closure": "PROVEN"},
                    is_closed=bar.is_closed, is_complete=bar.is_complete,
                ))
            except ValueError:
                return blocked("BAR_EVENT_CANDIDATE_INVALID")
    if not candidates:
        return CanonicalBarEventIngressResult(
            "BLOCKED", 0, 0,
            ("BAR_EVENT_NO_QUALIFIED_SYMBOLS", *quarantined),
        )
    created = duplicates = 0
    try:
        for candidate in candidates:
            result = ledger.record(candidate, recorded_at=observed_at)
            created += int(result.created)
            duplicates += int(not result.created)
    except EventQueueFull:
        return blocked("BAR_EVENT_QUEUE_FULL", created, duplicates)
    except sqlite3.Error:
        return blocked("BAR_EVENT_STORAGE_FAILED", created, duplicates)
    except ValueError:
        return blocked("BAR_EVENT_FACT_CONFLICT", created, duplicates)
    if quarantined:
        return CanonicalBarEventIngressResult(
            "PARTIAL", created, duplicates, tuple(quarantined)
        )
    return CanonicalBarEventIngressResult(
        "RECORDED" if created else ("UNCHANGED" if duplicates else "NO_NEW_CLOSED_BAR"),
        created, duplicates,
    )

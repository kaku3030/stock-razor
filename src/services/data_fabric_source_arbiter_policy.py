"""Research-only, fail-closed US/CN Data Fabric source selection policy.

This returns one *proposed* authoritative source per symbol/timeframe. It does
not connect to a provider, publish to canonical, start a service, change Radar
admission, route orders or authorize trading. Provider qualification is external
and must be supplied as independently verified evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Iterable


_MARKET_SOURCES = {
    "US": frozenset({
        "DESKTOP_OPEND", "CLOUD_OPEND", "ALPACA_IEX", "TWELVE_DATA",
    }),
    "CN": frozenset({
        "DESKTOP_TICKFLOW", "CLOUD_TICKFLOW", "DESKTOP_GM",
        "DESKTOP_QMT", "TENCENT", "TDX", "EASTMONEY", "RQDATA",
    }),
}
_REQUIRED_GATES = (
    "reachable", "process_healthy", "entitlement_qualified",
    "freshness_qualified", "continuity_qualified",
    "completeness_qualified", "correctness_qualified",
    "source_progress_qualified",
)
_GATE_VALUES = frozenset({"PASS", "FAIL", "UNKNOWN"})


@dataclass(frozen=True)
class Candidate:
    """Externally produced evidence only. Missing/UNKNOWN is never PASS."""

    source: str
    market: str
    symbol: str
    timeframe: str
    observed_at_utc: datetime
    latency_ms: float | None
    source_age_ms: float | None
    sequence: int | None
    reachable: str = "UNKNOWN"
    process_healthy: str = "UNKNOWN"
    entitlement_qualified: str = "UNKNOWN"
    freshness_qualified: str = "UNKNOWN"
    continuity_qualified: str = "UNKNOWN"
    completeness_qualified: str = "UNKNOWN"
    correctness_qualified: str = "UNKNOWN"
    source_progress_qualified: str = "UNKNOWN"
    crosscheck_status: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if self.market not in _MARKET_SOURCES:
            raise ValueError("unsupported market")
        if self.source not in _MARKET_SOURCES[self.market]:
            raise ValueError("unknown or wrong-market provider")
        if not self.symbol.strip() or not self.timeframe.strip():
            raise ValueError("symbol and timeframe required")
        if self.observed_at_utc.tzinfo is None or self.observed_at_utc.utcoffset() is None:
            raise ValueError("observed_at_utc must be timezone aware")
        for gate in (*_REQUIRED_GATES, "crosscheck_status"):
            if getattr(self, gate) not in _GATE_VALUES:
                raise ValueError(f"{gate} must be PASS/FAIL/UNKNOWN")
        for key in ("latency_ms", "source_age_ms"):
            value = getattr(self, key)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{key} must be finite nonnegative or None")
        if self.sequence is not None and (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ValueError("sequence must be nonnegative integer or None")

    def qualification_missing(self, *, max_age_ms: float) -> tuple[str, ...]:
        missing = tuple(
            gate for gate in _REQUIRED_GATES if getattr(self, gate) != "PASS"
        )
        if self.latency_ms is None:
            missing += ("MEASURED_LATENCY_UNAVAILABLE",)
        if self.sequence is None:
            missing += ("SOURCE_SEQUENCE_UNAVAILABLE",)
        if self.source_age_ms is None:
            missing += ("SOURCE_AGE_UNAVAILABLE",)
        elif self.source_age_ms > max_age_ms:
            missing += ("SOURCE_AGE_OVER_LIMIT",)
        return missing


def propose_authoritative_source(
    market: str,
    symbol: str,
    timeframe: str,
    candidates: Iterable[Candidate],
    *,
    now_utc: datetime,
    max_age_ms: float,
    max_observation_age_ms: float = 120_000,
    incumbent: str | None = None,
    min_switch_advantage_ms: float = 5.0,
) -> dict:
    """Choose the fastest qualified candidate, with optional anti-flap guard.

    No mutable canonical writer is acquired here; this is a dry-run proposal.
    Crosscheck status remains separate and does not become admission.
    """
    if market not in _MARKET_SOURCES or not symbol.strip() or not timeframe.strip():
        raise ValueError("invalid market or stream key")
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone aware")
    for label, value in (
        ("max_age_ms", max_age_ms),
        ("max_observation_age_ms", max_observation_age_ms),
        ("min_switch_advantage_ms", min_switch_advantage_ms),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
            raise ValueError(f"{label} must be finite and non-negative")
    if max_age_ms == 0 or max_observation_age_ms == 0:
        raise ValueError("age thresholds must be positive")
    if incumbent is not None and incumbent not in _MARKET_SOURCES[market]:
        raise ValueError("incumbent must be known to the market")

    normalized_now = now_utc.astimezone(timezone.utc)
    seen: set[str] = set()
    eligible: list[Candidate] = []
    rejection: dict[str, list[str]] = {}
    for source in candidates:
        if source.market != market or source.symbol != symbol or source.timeframe != timeframe:
            raise ValueError("candidate stream key mismatch")
        if source.source in seen:
            raise ValueError("duplicate source for a single writer stream")
        seen.add(source.source)
        absent = list(source.qualification_missing(max_age_ms=max_age_ms))
        evidence_age = (normalized_now - source.observed_at_utc.astimezone(timezone.utc)).total_seconds() * 1000
        if evidence_age < 0:
            absent.append("FUTURE_OBSERVATION")
        elif evidence_age > max_observation_age_ms:
            absent.append("STALE_QUALIFICATION_EVIDENCE")
        if absent:
            rejection[source.source] = absent
        else:
            eligible.append(source)
    eligible.sort(key=lambda c: (float(c.latency_ms), c.source))
    selected = eligible[0] if eligible else None
    reason = "NO_QUALIFIED_SOURCE"
    if selected is not None:
        reason = "FIRST_QUALIFIED_SOURCE" if incumbent is None else "FASTEST_QUALIFIED_SOURCE"
        if selected.source == incumbent:
            reason = "INCUMBENT_FASTEST"
        elif incumbent is not None:
            previous = next((item for item in eligible if item.source == incumbent), None)
            if previous is None:
                reason = "INCUMBENT_NOT_QUALIFIED"
            elif float(previous.latency_ms) - float(selected.latency_ms) < min_switch_advantage_ms:
                selected = previous
                reason = "INCUMBENT_HELD_ANTI_FLAP"
            else:
                reason = "FASTER_QUALIFIED_SOURCE"

    return {
        "schema": "stock_razor_research_only_source_arbiter_policy_v0_1",
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "decision": "SHADOW_PROPOSAL" if selected is not None else "BLOCKED",
        "proposed_source": selected.source if selected else None,
        "switch_reason": reason,
        "source_latency_ms": float(selected.latency_ms) if selected else None,
        "source_age_ms": float(selected.source_age_ms) if selected else None,
        "source_sequence": selected.sequence if selected else None,
        "crosscheck_status": selected.crosscheck_status if selected else "UNKNOWN",
        "rejected_source_reasons": rejection,
        "qualified_candidate_count": len(eligible),
        "canonical_write_authorized": False,
        "single_writer_lease_acquired": False,
        "data_qualification": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "can_confirm_signal": False,
        "live_trade": False,
    }

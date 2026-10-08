"""Quarantined TickFlow observation to Source Arbiter Shadow bridge.

This module accepts only a small, already-redacted observation envelope.  It
does not call TickFlow, write canonical data, select a runtime owner, or
authorize Radar/trading.  Missing qualification evidence stays UNKNOWN.
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any

from .data_fabric_source_arbiter_policy import Candidate, propose_authoritative_source


_SCHEMA = "stock_razor_tickflow_shadow_observation_v0_1"
_TIMEFRAMES = frozenset({"1m", "5m", "15m", "30m", "60m", "1d"})
_GATES = (
    "reachable", "process_healthy", "entitlement_qualified",
    "freshness_qualified", "continuity_qualified", "completeness_qualified",
    "correctness_qualified", "source_progress_qualified", "crosscheck_status",
)


def _required_text(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _nonnegative_number(payload: dict[str, Any], field: str) -> float | None:
    value = payload.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError(f"{field} must be finite and nonnegative or null")
    return float(value)


def build_shadow_candidate(payload: dict[str, Any]) -> Candidate:
    """Validate a redacted TickFlow observation and return one Shadow candidate."""
    if not isinstance(payload, dict) or payload.get("schema") != _SCHEMA:
        raise ValueError("unsupported TickFlow shadow schema")
    if payload.get("provider") != "TICKFLOW_SDK" or payload.get("market") != "CN":
        raise ValueError("TickFlow shadow provider or market is invalid")
    if payload.get("source") != "DESKTOP_TICKFLOW":
        raise ValueError("TickFlow shadow source is invalid")
    symbol = _required_text(payload, "symbol").upper()
    if len(symbol) != 9 or not symbol[:6].isdigit() or symbol[-3:] not in {".SH", ".SZ", ".BJ"}:
        raise ValueError("symbol must be a CN exchange-suffixed code")
    timeframe = _required_text(payload, "timeframe")
    if timeframe not in _TIMEFRAMES:
        raise ValueError("unsupported timeframe")
    observed_at = datetime.fromisoformat(_required_text(payload, "observed_at_utc"))
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone aware")
    gates = {name: payload.get(name, "UNKNOWN") for name in _GATES}
    if any(value not in {"PASS", "FAIL", "UNKNOWN"} for value in gates.values()):
        raise ValueError("qualification gates must be PASS, FAIL, or UNKNOWN")
    sequence = payload.get("sequence")
    if sequence is not None and (isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0):
        raise ValueError("sequence must be a nonnegative integer or null")
    return Candidate(
        source="DESKTOP_TICKFLOW", market="CN", symbol=symbol, timeframe=timeframe,
        observed_at_utc=observed_at,
        latency_ms=_nonnegative_number(payload, "latency_ms"),
        source_age_ms=_nonnegative_number(payload, "source_age_ms"),
        sequence=sequence,
        **gates,
    )


def propose_tickflow_shadow(
    payload: dict[str, Any], *, now_utc: datetime, max_age_ms: float,
) -> dict[str, Any]:
    """Return the existing arbiter's dry-run result for one TickFlow observation."""
    candidate = build_shadow_candidate(payload)
    return propose_authoritative_source(
        "CN", candidate.symbol, candidate.timeframe, [candidate],
        now_utc=now_utc, max_age_ms=max_age_ms,
    )

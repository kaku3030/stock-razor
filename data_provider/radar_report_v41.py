"""Fail-closed V4.1 report assembly for independent Windows/AWS evidence.

This module performs no provider I/O and makes no trade decisions.  It accepts
already collected evidence and only exposes market observations when both
authorized endpoints agree on all five required timeframes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIMEFRAMES = ("1m", "5m", "15m", "1H", "D1")
MARKET_PROVIDER = {"CN": "TickFlow", "US": "OpenD"}
ENDPOINTS = ("WINDOWS", "AWS")
TIMING_PHASES = (
    "windows_fetch_ms", "aws_fetch_ms", "validation_ms",
    "technical_analysis_ms", "radar_scan_ms", "report_generation_ms",
    "end_to_end_ms",
)
MAX_BAR_AGE_SECONDS = {"1m": 180, "5m": 600, "15m": 1800, "1H": 7200, "D1": 172800}
_SHA = re.compile(r"^[0-9a-f]{40,64}$")


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _bar_errors(bar: Any, observed_at: datetime, timeframe: str) -> list[str]:
    if not isinstance(bar, dict):
        return ["MISSING_BAR"]
    errors = []
    stamp = _utc(bar.get("bar_end_utc"))
    if stamp is None:
        errors.append("BAR_TIMESTAMP_INVALID")
    elif stamp > observed_at:
        errors.append("BAR_TIMESTAMP_IN_FUTURE")
    if bar.get("is_closed") is not True:
        errors.append("BAR_NOT_CLOSED")
    if bar.get("continuity") != "PASS":
        errors.append("BAR_CONTINUITY_NOT_VERIFIED")
    values = [bar.get(key) for key in ("open", "high", "low", "close", "volume")]
    if not all(_finite(item) for item in values):
        errors.append("BAR_OHLCV_INVALID")
    else:
        open_, high, low, close, volume = values
        if min(open_, high, low, close) <= 0 or volume < 0:
            errors.append("BAR_OHLCV_INVALID")
        elif high < max(open_, low, close) or low > min(open_, high, close):
            errors.append("BAR_OHLC_INVALID")
    freshness_checked = _utc(bar.get("freshness_checked_at_utc"))
    if freshness_checked is None:
        errors.append("BAR_FRESHNESS_NOT_MEASURED")
    elif freshness_checked > observed_at:
        errors.append("BAR_FRESHNESS_TIMESTAMP_INVALID")
    age = bar.get("age_seconds")
    limit = bar.get("max_age_seconds")
    if not (_finite(age) and _finite(limit) and age >= 0 and 0 < limit <= MAX_BAR_AGE_SECONDS[timeframe] and age <= limit):
        errors.append("BAR_STALE_OR_FRESHNESS_INVALID")
    elif stamp is not None:
        measured_age = max(0.0, (observed_at - stamp).total_seconds())
        if measured_age > limit or abs(measured_age - age) > 5:
            errors.append("BAR_STALE_OR_FRESHNESS_INVALID")
    return errors


def _endpoint_errors(market: str, name: str, endpoint: Any) -> list[str]:
    errors = []
    if not isinstance(endpoint, dict):
        return [f"{name}_ENDPOINT_MISSING"]
    if endpoint.get("provider") != MARKET_PROVIDER[market]:
        errors.append(f"{name}_PROVIDER_NOT_ALLOWED")
    if endpoint.get("endpoint_id") != name:
        errors.append(f"{name}_ENDPOINT_ID_MISMATCH")
    if endpoint.get("permission_status") != "VERIFIED":
        errors.append(f"{name}_PERMISSION_NOT_VERIFIED")
    provenance = endpoint.get("provenance")
    if not isinstance(provenance, dict):
        errors.append(f"{name}_PROVENANCE_MISSING")
        provenance = {}
    if not isinstance(provenance.get("endpoint"), str) or not provenance.get("endpoint"):
        errors.append(f"{name}_SOURCE_ENDPOINT_MISSING")
    for key in ("repo_sha", "runtime_sha"):
        if not isinstance(provenance.get(key), str) or not _SHA.fullmatch(provenance[key]):
            errors.append(f"{name}_{key.upper()}_INVALID")
    if _utc(provenance.get("observed_at_utc")) is None:
        errors.append(f"{name}_OBSERVED_AT_INVALID")
    latency = provenance.get("request_latency_ms")
    if not (_finite(latency) and latency >= 0):
        errors.append(f"{name}_REQUEST_LATENCY_NOT_MEASURED")
    session = endpoint.get("market_session")
    if not isinstance(session, dict) or not all(
        isinstance(session.get(key), str) and session.get(key)
        for key in ("state", "timezone", "session_date")
    ):
        errors.append(f"{name}_SESSION_NOT_VERIFIED")
    elif session.get("state") not in {"OPEN", "CLOSED", "PRE_MARKET", "AFTER_HOURS", "BREAK"}:
        errors.append(f"{name}_SESSION_NOT_VERIFIED")
    else:
        try:
            ZoneInfo(session["timezone"])
        except (ZoneInfoNotFoundError, TypeError):
            errors.append(f"{name}_SESSION_TIMEZONE_INVALID")
    bars = endpoint.get("bars")
    if not isinstance(bars, dict):
        bars = {}
    for timeframe in TIMEFRAMES:
        if timeframe not in bars:
            errors.append(f"{name}_{timeframe}_MISSING")
            continue
        observed_at = _utc(provenance.get("observed_at_utc"))
        if observed_at:
            errors.extend(f"{name}_{timeframe}_{reason}" for reason in _bar_errors(bars[timeframe], observed_at, timeframe))
    if endpoint.get("fallback_from") not in (None, ""):
        errors.append(f"{name}_PROVIDER_FALLBACK_PROHIBITED")
    return errors


def _agreement_errors(evidence: Any) -> list[str]:
    if not isinstance(evidence, dict):
        return ["DUAL_ENDPOINT_EVIDENCE_MISSING"]
    windows, aws = evidence.get("WINDOWS"), evidence.get("AWS")
    if not isinstance(windows, dict) or not isinstance(aws, dict):
        return ["DUAL_ENDPOINT_EVIDENCE_MISSING"]
    errors = []
    window_bars = windows.get("bars")
    aws_bars = aws.get("bars")
    window_bars = window_bars if isinstance(window_bars, dict) else {}
    aws_bars = aws_bars if isinstance(aws_bars, dict) else {}
    for timeframe in TIMEFRAMES:
        wb = window_bars.get(timeframe)
        ab = aws_bars.get(timeframe)
        if not isinstance(wb, dict) or not isinstance(ab, dict):
            continue
        keys = ("bar_end_utc", "open", "high", "low", "close", "volume")
        if any(wb.get(key) != ab.get(key) for key in keys):
            errors.append(f"DUAL_ENDPOINT_{timeframe}_DISAGREEMENT")
    return errors


def _project_endpoint_evidence(evidence: Any) -> dict:
    """Return only contract fields; never echo opaque provider payloads."""
    projected = {}
    if not isinstance(evidence, dict):
        return projected
    for name in ENDPOINTS:
        endpoint = evidence.get(name)
        if not isinstance(endpoint, dict):
            continue
        provenance = endpoint.get("provenance")
        provenance = provenance if isinstance(provenance, dict) else {}
        session = endpoint.get("market_session")
        session = session if isinstance(session, dict) else {}
        bars = endpoint.get("bars")
        bars = bars if isinstance(bars, dict) else {}
        projected[name] = {
            "provider": endpoint.get("provider"),
            "endpoint_id": endpoint.get("endpoint_id"),
            "permission_status": endpoint.get("permission_status"),
            "fallback_from": endpoint.get("fallback_from"),
            "market_session": {key: session.get(key) for key in ("state", "timezone", "session_date")},
            "provenance": {key: provenance.get(key) for key in (
                "endpoint", "repo_sha", "runtime_sha", "observed_at_utc", "request_latency_ms"
            )},
            "bars": {
                frame: ({key: bars[frame].get(key) for key in (
                    "bar_end_utc", "open", "high", "low", "close", "volume",
                    "is_closed", "continuity", "freshness_checked_at_utc",
                    "age_seconds", "max_age_seconds",
                )} if isinstance(bars.get(frame), dict) else None)
                for frame in TIMEFRAMES if frame in bars
            },
        }
    return projected


def build_report(
    market: str,
    symbol: str,
    endpoint_evidence: Any,
    *,
    holdings: list[dict] | None = None,
    opportunities: list[dict] | None = None,
    conditional_plans: list[dict] | None = None,
    timings: dict | None = None,
) -> dict:
    """Assemble a Main Control report; invalid evidence yields no candidates."""
    market = market.upper() if isinstance(market, str) else ""
    errors = []
    if market not in MARKET_PROVIDER:
        errors.append("MARKET_NOT_SUPPORTED")
    if not isinstance(symbol, str) or not symbol.strip():
        errors.append("SYMBOL_INVALID")
    if market in MARKET_PROVIDER:
        if not isinstance(endpoint_evidence, dict):
            errors.append("DUAL_ENDPOINT_EVIDENCE_MISSING")
        else:
            for endpoint in ENDPOINTS:
                errors.extend(_endpoint_errors(market, endpoint, endpoint_evidence.get(endpoint)))
            errors.extend(_agreement_errors(endpoint_evidence))

    measured = {}
    if not isinstance(timings, dict):
        timings = {}
    for phase in TIMING_PHASES:
        value = timings.get(phase)
        measured[phase] = round(float(value), 3) if _finite(value) and value >= 0 else "NOT_MEASURED"
    if any(measured[key] == "NOT_MEASURED" for key in TIMING_PHASES):
        errors.append("TIMING_FIELDS_INCOMPLETE")
    elif measured["end_to_end_ms"] < max(measured[key] for key in TIMING_PHASES[:-1]):
        errors.append("END_TO_END_TIMING_INCONSISTENT")

    holdings_state = "VERIFIED" if isinstance(holdings, list) and holdings and all(
        isinstance(item, dict) and item.get("verification") == "VERIFIED"
        and isinstance(item.get("quantity_as_of_utc"), str)
        and _utc(item["quantity_as_of_utc"]) is not None for item in holdings
    ) else "USER_REPORTED_OR_UNKNOWN"
    safe_holdings = []
    if isinstance(holdings, list):
        for item in holdings:
            if isinstance(item, dict):
                safe_holdings.append({key: item.get(key) for key in (
                    "symbol", "quantity", "quantity_as_of_utc", "verification", "source"
                )})

    accepted = not errors
    candidates = opportunities if accepted and isinstance(opportunities, list) else []
    plans = conditional_plans if accepted and isinstance(conditional_plans, list) else []
    feedback_material = json.dumps(
        {"market": market, "symbol": symbol, "reasons": sorted(set(errors))},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema": "stock_razor_unified_radar_report_v4_1",
        "status": "PASS_RESEARCH_ONLY" if accepted else "BLOCKED",
        "market": market or "UNKNOWN",
        "symbol": symbol.strip().upper() if isinstance(symbol, str) else "UNKNOWN",
        "data_acceptance": "PASS" if accepted else "NOT_VERIFIED",
        "provider": MARKET_PROVIDER.get(market, "UNKNOWN"),
        "timeframes": list(TIMEFRAMES),
        "endpoint_evidence": _project_endpoint_evidence(endpoint_evidence),
        "performance": measured,
        "holdings": {"status": holdings_state, "items": safe_holdings},
        "opportunities": candidates,
        "conditional_plans": plans,
        "execution": "NONE",
        "feedback": {
            "dedupe_key": hashlib.sha256(feedback_material).hexdigest(),
            "status": "READY_FOR_FEEDBACK_HUB" if errors else "NO_DEFECT",
            "reasons": sorted(set(errors)),
        },
        "safety": {
            "research_only": True, "live_trade": False,
            "trade_execution": False, "radar_admission": "BLOCKED",
            "source_arbiter_admission": "BLOCKED", "paper_auto_ready": False,
        },
    }


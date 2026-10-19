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
_SAFE_ENDPOINT = re.compile(r"^[A-Za-z0-9._:/-]{1,120}$")
_CN_SYMBOL = re.compile(r"^[0-9]{6}(?:\.(?:SH|SZ|BJ))?$")
_US_SYMBOL = re.compile(r"^(?:US\.)?[A-Z0-9._-]{1,16}$")


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
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _valid_symbol(value: Any, market: str) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().upper()
    if market == "CN":
        return bool(_CN_SYMBOL.fullmatch(normalized))
    if market == "US":
        return bool(_US_SYMBOL.fullmatch(normalized))
    return False


def _bar_errors(
    bar: Any, observed_at: datetime, report_completed_at: datetime,
    timeframe: str,
) -> list[str]:
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
    elif abs((freshness_checked - observed_at).total_seconds()) > 5:
        errors.append("BAR_FRESHNESS_TIMESTAMP_INVALID")
    age = bar.get("age_seconds")
    limit = bar.get("max_age_seconds")
    valid_age = (
        _finite(age) and _finite(limit) and age >= 0
        and 0 < limit <= MAX_BAR_AGE_SECONDS[timeframe] and age <= limit
    )
    if not valid_age:
        errors.append("BAR_STALE_OR_FRESHNESS_INVALID")
    elif stamp is not None:
        measured_age = max(0.0, (observed_at - stamp).total_seconds())
        report_age = max(0.0, (report_completed_at - stamp).total_seconds())
        if (
            measured_age > limit or report_age > MAX_BAR_AGE_SECONDS[timeframe]
            or abs(measured_age - age) > 5
        ):
            errors.append("BAR_STALE_OR_FRESHNESS_INVALID")
    return errors


def _endpoint_errors(
    market: str, name: str, endpoint: Any, received_at: datetime | None,
    report_completed_at: datetime | None,
) -> list[str]:
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
    observed_at = _utc(provenance.get("observed_at_utc"))
    if observed_at is None:
        errors.append(f"{name}_OBSERVED_AT_INVALID")
    elif (
        received_at and report_completed_at
        and not received_at <= observed_at <= report_completed_at
    ):
        errors.append(f"{name}_OBSERVATION_OUTSIDE_REPORT_WINDOW")
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
        try:
            datetime.strptime(session["session_date"], "%Y-%m-%d")
        except (TypeError, ValueError):
            errors.append(f"{name}_SESSION_DATE_INVALID")
    bars = endpoint.get("bars")
    if not isinstance(bars, dict):
        bars = {}
    for timeframe in TIMEFRAMES:
        if timeframe not in bars:
            errors.append(f"{name}_{timeframe}_MISSING")
            continue
        if observed_at and report_completed_at:
            errors.extend(f"{name}_{timeframe}_{reason}" for reason in _bar_errors(
                bars[timeframe], observed_at, report_completed_at, timeframe
            ))
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
    ws, aws_session = windows.get("market_session"), aws.get("market_session")
    if isinstance(ws, dict) and isinstance(aws_session, dict):
        if any(
            ws.get(key) != aws_session.get(key)
            for key in ("state", "timezone", "session_date")
        ):
            errors.append("DUAL_ENDPOINT_SESSION_DISAGREEMENT")
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
        endpoint_provider = endpoint.get("provider")
        if endpoint_provider not in MARKET_PROVIDER.values():
            endpoint_provider = "UNKNOWN"
        endpoint_name = provenance.get("endpoint")
        if not (
            isinstance(endpoint_name, str)
            and _SAFE_ENDPOINT.fullmatch(endpoint_name)
        ):
            endpoint_name = "UNKNOWN"
        timestamp = _utc(provenance.get("observed_at_utc"))
        repo_sha = provenance.get("repo_sha")
        runtime_sha = provenance.get("runtime_sha")
        session_timezone = session.get("timezone")
        try:
            ZoneInfo(session_timezone)
        except (ZoneInfoNotFoundError, TypeError):
            session_timezone = "UNKNOWN"
        session_state = session.get("state")
        if session_state not in {"OPEN", "CLOSED", "PRE_MARKET", "AFTER_HOURS", "BREAK"}:
            session_state = "UNKNOWN"
        try:
            datetime.strptime(session.get("session_date", ""), "%Y-%m-%d")
            session_date = session["session_date"]
        except (TypeError, ValueError):
            session_date = "UNKNOWN"
        projected[name] = {
            "provider": endpoint_provider,
            "endpoint_id": name,
            "permission_status": (
                "VERIFIED" if endpoint.get("permission_status") == "VERIFIED"
                else "UNVERIFIED"
            ),
            "fallback_from": "PRESENT" if endpoint.get("fallback_from") not in (None, "") else None,
            "market_session": {
                "state": session_state, "timezone": session_timezone,
                "session_date": session_date,
            },
            "provenance": {
                "endpoint": endpoint_name,
                "repo_sha": (
                    repo_sha if isinstance(repo_sha, str) and _SHA.fullmatch(repo_sha)
                    else "UNKNOWN"
                ),
                "runtime_sha": (
                    runtime_sha if isinstance(runtime_sha, str) and _SHA.fullmatch(runtime_sha)
                    else "UNKNOWN"
                ),
                "observed_at_utc": timestamp.isoformat() if timestamp else "UNKNOWN",
                "request_latency_ms": (
                    float(provenance["request_latency_ms"])
                    if _finite(provenance.get("request_latency_ms"))
                    and provenance["request_latency_ms"] >= 0 else None
                ),
            },
            "bars": {
                frame: _project_bar(bars.get(frame)) for frame in TIMEFRAMES
                if frame in bars
            },
        }
    return projected


def _project_bar(bar: Any) -> dict | None:
    if not isinstance(bar, dict):
        return None
    bar_stamp = _utc(bar.get("bar_end_utc"))
    freshness_stamp = _utc(bar.get("freshness_checked_at_utc"))
    return {
        "bar_end_utc": bar_stamp.isoformat() if bar_stamp else "UNKNOWN",
        **{
            key: float(bar[key]) if _finite(bar.get(key)) else None
            for key in ("open", "high", "low", "close", "volume")
        },
        "is_closed": bar.get("is_closed") if type(bar.get("is_closed")) is bool else None,
        "continuity": "PASS" if bar.get("continuity") == "PASS" else "UNKNOWN",
        "freshness_checked_at_utc": freshness_stamp.isoformat() if freshness_stamp else "UNKNOWN",
        "age_seconds": (
            float(bar["age_seconds"])
            if _finite(bar.get("age_seconds")) and bar["age_seconds"] >= 0 else None
        ),
        "max_age_seconds": (
            float(bar["max_age_seconds"])
            if _finite(bar.get("max_age_seconds")) and bar["max_age_seconds"] > 0 else None
        ),
    }


def build_report(
    market: str,
    symbol: str,
    endpoint_evidence: Any,
    *,
    holdings: list[dict] | None = None,
    opportunities: list[dict] | None = None,
    conditional_plans: list[dict] | None = None,
    timings: dict | None = None,
    received_at_utc: str | None = None,
    report_completed_at_utc: str | None = None,
) -> dict:
    """Assemble a Main Control report; invalid evidence yields no candidates."""
    market = market.upper() if isinstance(market, str) else ""
    errors = []
    if market not in MARKET_PROVIDER:
        errors.append("MARKET_NOT_SUPPORTED")
    normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
    symbol_valid = _valid_symbol(normalized_symbol, market)
    if not symbol_valid:
        errors.append("SYMBOL_INVALID")
    if market in MARKET_PROVIDER:
        received_at = _utc(received_at_utc)
        report_completed_at = _utc(report_completed_at_utc)
        if received_at is None or report_completed_at is None or report_completed_at < received_at:
            errors.append("REPORT_TIME_WINDOW_INVALID")
        if not isinstance(endpoint_evidence, dict):
            errors.append("DUAL_ENDPOINT_EVIDENCE_MISSING")
        else:
            for endpoint in ENDPOINTS:
                errors.extend(_endpoint_errors(
                    market, endpoint, endpoint_evidence.get(endpoint),
                    received_at, report_completed_at,
                ))
            errors.extend(_agreement_errors(endpoint_evidence))
    else:
        received_at = _utc(received_at_utc)
        report_completed_at = _utc(report_completed_at_utc)

    measured = {}
    if not isinstance(timings, dict):
        timings = {}
    for phase in TIMING_PHASES:
        value = timings.get(phase)
        measured[phase] = (
            round(float(value), 3)
            if _finite(value) and value >= 0 else "NOT_MEASURED"
        )
    if any(measured[key] == "NOT_MEASURED" for key in TIMING_PHASES):
        errors.append("TIMING_FIELDS_INCOMPLETE")
    elif measured["end_to_end_ms"] < max(measured[key] for key in TIMING_PHASES[:-1]):
        errors.append("END_TO_END_TIMING_INCONSISTENT")
    if received_at is None or report_completed_at is None or report_completed_at < received_at:
        errors.append("REPORT_TIME_WINDOW_INVALID")
        actual_end_to_end_ms = "NOT_MEASURED"
    else:
        actual_end_to_end_ms = round((report_completed_at - received_at).total_seconds() * 1000, 3)
        if measured["end_to_end_ms"] != "NOT_MEASURED" and abs(
            measured["end_to_end_ms"] - actual_end_to_end_ms
        ) > max(10.0, actual_end_to_end_ms * 0.1):
            errors.append("END_TO_END_TIMING_TIMESTAMP_MISMATCH")
    measured["received_at_utc"] = received_at_utc if received_at else "NOT_MEASURED"
    measured["report_completed_at_utc"] = (
        report_completed_at_utc if report_completed_at else "NOT_MEASURED"
    )
    measured["end_to_end_ms"] = actual_end_to_end_ms

    holdings_state = "VERIFIED" if isinstance(holdings, list) and holdings and all(
        isinstance(item, dict) and item.get("verification") == "VERIFIED"
        and _valid_symbol(item.get("symbol"), market)
        and _finite(item.get("quantity")) and item["quantity"] >= 0
        and isinstance(item.get("quantity_as_of_utc"), str)
        and _utc(item["quantity_as_of_utc"]) is not None
        and isinstance(item.get("source"), str) and _SAFE_ENDPOINT.fullmatch(item["source"])
        for item in holdings
    ) else "USER_REPORTED_OR_UNKNOWN"
    safe_holdings = []
    if isinstance(holdings, list):
        for item in holdings:
            if isinstance(item, dict):
                stamp = _utc(item.get("quantity_as_of_utc"))
                source = item.get("source")
                safe_holdings.append({
                    "symbol": (
                        item["symbol"].strip().upper()
                        if _valid_symbol(item.get("symbol"), market) else "UNKNOWN"
                    ),
                    "quantity": (
                        float(item["quantity"])
                        if _finite(item.get("quantity")) and item["quantity"] >= 0
                        else None
                    ),
                    "quantity_as_of_utc": stamp.isoformat() if stamp else "UNKNOWN",
                    "verification": (
                        "VERIFIED" if item.get("verification") == "VERIFIED"
                        else "USER_REPORTED_OR_UNKNOWN"
                    ),
                    "source": (
                        source if isinstance(source, str) and _SAFE_ENDPOINT.fullmatch(source)
                        else "UNKNOWN"
                    ),
                })

    accepted = not errors
    candidates = opportunities if accepted and isinstance(opportunities, list) else []
    plans = conditional_plans if accepted and isinstance(conditional_plans, list) else []
    feedback_material = json.dumps(
        {
            "market": market,
            "symbol": normalized_symbol if symbol_valid else "UNKNOWN",
            "reasons": sorted(set(errors)),
        },
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return {
        "schema": "stock_razor_unified_radar_report_v4_1",
        "status": "PASS_RESEARCH_ONLY" if accepted else "BLOCKED",
        "market": market or "UNKNOWN",
        "symbol": normalized_symbol if symbol_valid else "UNKNOWN",
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

_FEEDBACK_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")


def submit_report_feedback(report: Any, feedback_hub: Any) -> Any:
    """Idempotently submit a sanitized V4.1 acceptance defect to Feedback Hub.

    The hub is injected by the caller so this contract has no database or
    provider dependency. Raw bars, holdings, opportunities, and provider
    payloads are never copied into the Feedback Hub record.
    """
    if (
        not isinstance(report, dict)
        or report.get("schema") != "stock_razor_unified_radar_report_v4_1"
    ):
        raise ValueError("report is not a V4.1 Main Control report")
    feedback = report.get("feedback")
    if not isinstance(feedback, dict):
        raise ValueError("report feedback contract is missing")
    status = feedback.get("status")
    if status == "NO_DEFECT":
        if report.get("status") != "PASS_RESEARCH_ONLY":
            raise ValueError("report status conflicts with feedback status")
        return None
    if status != "READY_FOR_FEEDBACK_HUB" or report.get("status") != "BLOCKED":
        raise ValueError("report is not a blocked V4.1 acceptance defect")

    market = report.get("market")
    symbol = report.get("symbol")
    reasons = feedback.get("reasons")
    dedupe_key = feedback.get("dedupe_key")
    if (
        not isinstance(market, str)
        or market not in MARKET_PROVIDER
        or not _valid_symbol(symbol, market)
        or not isinstance(reasons, list)
        or not reasons
        or len(reasons) > 120
        or any(
            not isinstance(reason, str) or not _FEEDBACK_REASON.fullmatch(reason)
            for reason in reasons
        )
        or not isinstance(dedupe_key, str)
        or not re.fullmatch(r"[0-9a-f]{64}", dedupe_key)
    ):
        raise ValueError("report feedback fields are invalid")
    normalized_reasons = sorted(set(reasons))
    submit = getattr(feedback_hub, "submit", None)
    if not callable(submit):
        raise TypeError("feedback_hub must provide submit()")

    source = "CN_RADAR" if market == "CN" else "US_RADAR"
    source_ref = f"v41:{market}:{symbol}:{dedupe_key}"
    evidence = {
        "status": "BLOCKED",
        "reason": "V4_1_ACCEPTANCE_DEFECT",
        "count": len(normalized_reasons),
        "checks": [{"reason": reason} for reason in normalized_reasons[:40]],
    }
    details = ";".join(normalized_reasons[:40])
    return submit(
        source=source,
        priority="P1",
        title="V4.1 dual-end evidence blocked",
        details=details,
        evidence=evidence,
        source_ref=source_ref,
        dedupe_key=dedupe_key,
    )

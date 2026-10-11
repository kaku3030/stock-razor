"""Fail-closed read-only view of the latest isolated TickFlow AWS probe.

This is *probe evidence*, not a production TickFlow feed or market-data admission.
Never perform TickFlow I/O or expose credential/provider payloads from MCP.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os

DEFAULT_PATH = "/opt/stock-razor-tickflow-premium-probe/last-sanitized-probe.json"
MAX_BYTES = 32768
MAX_AGE_SECONDS = 3600
SAFE_OPERATIONS = frozenset((
    "sdk_import", "free_daily_kline", "realtime_quote", "kline_1m",
    "kline_5m", "kline_15m", "kline_30m", "kline_60m",
    "five_level_depth", "websocket_quote_smoke",
))
SAFE_PROBE_SCHEMAS = frozenset((
    "stock_razor_tickflow_sanitized_probe_v0_1",
    "stock_razor_tickflow_isolated_probe_v0_1",
))
SAFE_ISOLATED_MODES = frozenset(("metadata", "free", "premium-contract"))

# Direct MCP access must not forward *arbitrary* even short strings from cache.
# All allowed values below are fixed protocol vocabulary, not provider text.
SAFE_WS_DIAGNOSTIC_VALUES = frozenset((
    "UNKNOWN", "PASS", "FAILED", "BLOCKED", "NOT_VERIFIED", "PROVEN",
    "UNPROVEN", "OBSERVED", "NO_EVENTS_OBSERVED", "NOT_APPLICABLE",
    "CONNECTED", "DISCONNECTED", "CONNECTING", "SUBSCRIBED",
    "POST_INITIAL_CANDIDATES_ONLY_NOT_VERIFIED_LIVE",
    "NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK",
))
SAFE_HISTORICAL_SUMMARY_ENUMS = {
    "timestamp_monotonicity": frozenset(("STRICTLY_INCREASING", "NON_MONOTONIC", "NOT_VERIFIED", "UNKNOWN")),
    "closure": frozenset(("NOT_VERIFIED", "PROVEN", "UNPROVEN", "PASS", "BLOCKED")),
    "freshness": frozenset(("NOT_VERIFIED", "PROVEN", "UNPROVEN", "PASS", "BLOCKED")),
    "entitlement_evidence": frozenset(("NOT_VERIFIED", "UNKNOWN", "PASS", "BLOCKED")),
    "period": frozenset(("1d",)),
}



def read_tickflow_probe_health(path: str | None = None, *,
                               now_utc: datetime | None = None,
                               max_age_seconds: int = MAX_AGE_SECONDS) -> dict:
    """Read a bounded, previously sanitized file; no API, secrets or subscriptions."""
    common = {
        "research_only": True,
        "production_tickflow_feed": False,
        "tickflow_to_radar_e2e": "NOT_VERIFIED",
        "data_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "can_confirm_signal": False,
        "live_trade": False,
        "provider_requests": 0,
    }

    def fail(status: str) -> dict:
        return {**common, "ok": False, "status": status}

    selected = path or os.environ.get("STOCK_RAZOR_TICKFLOW_PROBE_CACHE_PATH", DEFAULT_PATH)
    try:
        with open(selected, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return fail("INVALID")
        payload = json.loads(raw)
    except (OSError, ValueError, TypeError, UnicodeError):
        return fail("UNAVAILABLE")

    if (not isinstance(payload, dict) or not isinstance(payload.get("schema"), str)
            or payload.get("schema") not in SAFE_PROBE_SCHEMAS):
        return fail("INVALID")
    schema = payload.get("schema")
    mode = payload.get("mode")
    if type(payload.get("operations")) is not list:
        return fail("INVALID")
    if schema == "stock_razor_tickflow_sanitized_probe_v0_1":
        if mode != "premium":
            return fail("INVALID")
    elif (
        not isinstance(mode, str) or mode not in SAFE_ISOLATED_MODES
        or payload.get("location") != "AWS_TOKYO_SSM_ISOLATE"
    ):
        return fail("INVALID")
    if len(payload["operations"]) > 20:
        return fail("INVALID")
    try:
        observed = datetime.fromisoformat(payload["observed_at_utc"])
        now = now_utc or datetime.now(timezone.utc)
        if observed.tzinfo is None or observed.utcoffset() is None:
            return fail("INVALID")
        if now.tzinfo is None or now.utcoffset() is None:
            return fail("INVALID")
        age = (now.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
    except (KeyError, TypeError, ValueError, OverflowError):
        return fail("INVALID")
    if age < 0 or age > max_age_seconds:
        return {**fail("STALE"), "age_seconds": round(age, 2)}

    ops = []
    for op in payload["operations"]:
        if (not isinstance(op, dict) or not isinstance(op.get("name"), str)
                or op.get("name") not in SAFE_OPERATIONS):
            return fail("INVALID")
        name, state = op["name"], op.get("operation")
        if not isinstance(state, str) or state not in ("COMPLETED", "NO_EVENTS_OBSERVED", "OBSERVED", "CLOSE_FAILED", "FAILED", "BLOCKED", "SKIPPED", "ERROR"):
            return fail("INVALID")
        item = {"name": name, "operation": state}
        for field in ("elapsed_ms", "row_count"):
            val = op.get(field)
            if type(val) in (int, float) and 0 <= val <= 1e8:
                item[field] = val
        if type(op.get("schema_qualified")) is bool:
            item["schema_qualified"] = op["schema_qualified"]
        for field in ("freshness", "closure"):
            val = op.get(field)
            if val in ("NOT_VERIFIED", "PROVEN", "UNPROVEN", "PASS", "BLOCKED"):
                item[field] = val
        if name == "websocket_quote_smoke":
            for field in (
                "quote_callbacks", "quote_events", "unique_quote_samples",
                "initial_snapshot_candidates", "post_initial_update_candidates",
                "duplicate_timestamp_events", "out_of_order_timestamp_events",
                "unrequested_symbol_events", "invalid_timestamp_events",
                "error_callbacks",
            ):
                val = op.get(field)
                if type(val) is int and 0 <= val <= 100000000:
                    item[field] = val
            for field in (
                "connection_state", "subscription_state", "event_state",
                "lag_scope", "subscribed_ack_evidence",
                "snapshot_vs_live_evidence", "ping_pong_evidence",
                "reconnect_resubscribe_evidence", "sample_latency_qualification",
                "clock_offset_qualification",
            ):
                val = op.get(field)
                if isinstance(val, str) and val in SAFE_WS_DIAGNOSTIC_VALUES:
                    item[field] = val
            for field in ("continuous_feed_qualified", "stale_drop_reconnect_qualified"):
                if type(op.get(field)) is bool:
                    item[field] = op[field]
        ops.append(item)

    sha = payload.get("repo_sha")
    if not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        return fail("INVALID")
    historical = "NOT_REQUESTED"
    if schema == "stock_razor_tickflow_isolated_probe_v0_1":
        raw_historical = payload.get("historical_kline_observation")
        if not isinstance(raw_historical, dict):
            return fail("INVALID")
        summary = raw_historical.get("summary")
        safe_summary = None
        if isinstance(summary, dict):
            safe_summary = {}
            if type(summary.get("sample_count")) is int and 0 <= summary["sample_count"] <= 100000000:
                safe_summary["sample_count"] = summary["sample_count"]
            if type(summary.get("ohlcv_range_valid")) is bool:
                safe_summary["ohlcv_range_valid"] = summary["ohlcv_range_valid"]
            for field, allowed in SAFE_HISTORICAL_SUMMARY_ENUMS.items():
                value = summary.get(field)
                if isinstance(value, str) and value in allowed:
                    safe_summary[field] = value
        row_count = raw_historical.get("row_count")
        historical = {
            "operation": raw_historical.get("operation"),
            "period": raw_historical.get("period"),
            "row_count": row_count if type(row_count) is int and 0 <= row_count <= 100000000 else 0,
            "qualification": raw_historical.get("qualification"),
            "summary": safe_summary,
        }
        if (
            historical["operation"] not in ("COMPLETED", "FAILED", "SKIPPED")
            or historical["period"] != "1d"
            or historical["qualification"] != "NOT_VERIFIED"
        ):
            return fail("INVALID")
    return {
        **common,
        "ok": True,
        "status": "PROBE_ONLY",
        "age_seconds": round(age, 2),
        "observed_at_utc": observed.isoformat(),
        "repo_sha": sha,
        "data_qualification": "NOT_VERIFIED",
        "historical_kline_observation": historical,
        "operations": ops,
    }

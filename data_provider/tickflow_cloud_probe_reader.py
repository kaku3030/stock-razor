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
    "sdk_import", "realtime_quote", "kline_1m", "kline_5m", "kline_15m",
    "kline_30m", "kline_60m", "five_level_depth", "websocket_quote_smoke",
))


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

    if not isinstance(payload, dict) or payload.get("schema") != "stock_razor_tickflow_sanitized_probe_v0_1":
        return fail("INVALID")
    if payload.get("mode") != "premium" or type(payload.get("operations")) is not list:
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
        if not isinstance(op, dict) or op.get("name") not in SAFE_OPERATIONS:
            return fail("INVALID")
        name, state = op["name"], op.get("operation")
        if state not in ("COMPLETED", "NO_EVENTS_OBSERVED", "BLOCKED", "SKIPPED", "ERROR"):
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
        ops.append(item)

    sha = payload.get("repo_sha")
    if not isinstance(sha, str) or len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        return fail("INVALID")
    return {
        **common,
        "ok": True,
        "status": "PROBE_ONLY",
        "age_seconds": round(age, 2),
        "observed_at_utc": observed.isoformat(),
        "repo_sha": sha,
        "data_qualification": "NOT_VERIFIED",
        "operations": ops,
    }

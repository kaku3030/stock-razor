"""Offline JSON trace import for the read-only provider-to-device latency audit.

Usage: python -m scripts.notification_latency_json_audit < private-traces.json
Reads stdin only. Never sends notifications, calls providers, or writes files.
Prints aggregates without copying unknown input keys or event identifiers.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from src.services.stock_radar_v2.notification_latency_audit import (
    MAX_TRACES, STAGES, audit_market_to_notification_traces,
)

MAX_INPUT_BYTES = 2_000_000
_TIME_FIELDS = frozenset(STAGES)
_FIELDS = frozenset((
    "source_runtime_id", "source_sequence", "provider_timestamp_verified",
    "clock_sync_verified", "max_cross_host_clock_error_ms",
    "device_receipt_verified",
)) | _TIME_FIELDS


def _parse_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or len(raw) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def audit_json_bytes(payload: bytes) -> dict[str, Any]:
    """Validate bounded JSON; return aggregates only, never source payload."""
    safety = {
        "schema": "stock_razor_notification_latency_json_import_v0_1",
        "status": "BLOCKED",
        "research_only": True,
        "provider_requests": 0,
        "notification_sends": 0,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }

    def blocked(reason: str) -> dict[str, Any]:
        return {**safety, "reason": reason}

    if not isinstance(payload, bytes) or len(payload) > MAX_INPUT_BYTES:
        return blocked("INVALID_OR_OVERSIZED_INPUT")
    try:
        raw = json.loads(payload)
    except (ValueError, UnicodeDecodeError, TypeError, RecursionError):
        return blocked("INVALID_JSON")
    if not isinstance(raw, list) or len(raw) > MAX_TRACES:
        return blocked("INVALID_TRACE_LIST")

    traces: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            traces.append({})
            continue
        # Whitelist fields: no account, ticker, key, event body or PII in
        # resulting trace dictionaries, even transiently.
        trace = {k: item[k] for k in _FIELDS if k in item}
        for key in _TIME_FIELDS:
            if key in trace:
                trace[key] = _parse_datetime(trace[key])
        traces.append(trace)
    return audit_market_to_notification_traces(traces)


def main() -> int:
    payload = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    result = audit_json_bytes(payload)
    sys.stdout.write(json.dumps(result, sort_keys=True, allow_nan=False) + "\n")
    return 0 if result["status"] == "OBSERVATIONAL_ONLY" else 2


if __name__ == "__main__":
    raise SystemExit(main())

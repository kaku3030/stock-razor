"""Lightweight fail-closed reader for Futures runtime heartbeat evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os

DEFAULT_STATUS_PATH = "/run/stock-razor-futures/latest-heartbeat.json"
DEFAULT_MAX_AGE_SECONDS = 180


def read_futures_runtime_health(path: str | None = None, *, now_utc: datetime | None = None,
                                max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS) -> dict:
    status_path = path or os.environ.get("STOCK_RAZOR_FUTURES_STATUS_PATH", DEFAULT_STATUS_PATH)
    try:
        with open(status_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError) as exc:
        return {"ok": False, "status": "UNAVAILABLE", "error": type(exc).__name__,
                "realtime_verified": False, "radar_admission": "BLOCKED", "live_trade": False}

    required = ("runtime_instance_id", "generation", "host_id", "sequence", "emitted_at_utc")
    if (not isinstance(payload, dict)
            or payload.get("type") != "futures_runtime_heartbeat"
            or any(key not in payload for key in required)):
        return {"ok": False, "status": "INVALID", "realtime_verified": False,
                "radar_admission": "BLOCKED", "live_trade": False}

    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    try:
        emitted = datetime.fromisoformat(payload["emitted_at_utc"])
        if emitted.tzinfo is None or emitted.utcoffset() is None:
            raise ValueError("naive timestamp")
        age = (now.astimezone(timezone.utc) - emitted.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        return {"ok": False, "status": "INVALID", "realtime_verified": False,
                "radar_admission": "BLOCKED", "live_trade": False}

    fresh = 0 <= age <= max_age_seconds
    return {
        "ok": fresh,
        "status": "HEALTHY" if fresh else "STALE",
        "age_seconds": age,
        "heartbeat": payload,
        "realtime_verified": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }

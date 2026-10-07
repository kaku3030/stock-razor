"""Fast fail-closed reader for cloud A-share observation snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from time import perf_counter


DEFAULT_STATUS_PATH = "/run/stock-razor-cn-eastmoney/latest-observation.json"
SUPPORTED_TIMEFRAMES = ("1d", "60m", "15m")


def _finish(started: float, payload: dict) -> dict:
    return {**payload, "read_latency_ms": round((perf_counter() - started) * 1000, 3)}


def _fail(status: str, *, error: str | None = None, **extra) -> dict:
    payload = {
        "ok": False,
        "status": status,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    if error is not None:
        payload["error"] = error
    payload.update(extra)
    return payload


def _load(path: str) -> tuple[dict | None, str | None]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError) as exc:
        return None, type(exc).__name__
    if not isinstance(payload, dict):
        return None, "INVALID_JSON_ROOT"
    return payload, None


def _symbol(value: object) -> str | None:
    raw = str(value or "").strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if raw.endswith(suffix):
            raw = raw[:-3]
            break
    if len(raw) == 6 and raw.isdigit():
        return raw
    return None


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def read_cn_market_bars(
    symbol: object,
    *,
    timeframe: str = "1d",
    limit: int = 100,
    path: str | None = None,
    now_utc: datetime | None = None,
    snapshot_max_age_seconds: int = 180,
) -> dict:
    """Read already-fetched cloud A-share rows with full provider provenance."""

    started = perf_counter()
    code = _symbol(symbol)
    if code is None:
        return _finish(started, _fail("INVALID_ARGUMENT", error="INVALID_SYMBOL"))

    frame = str(timeframe).strip().lower()
    if frame not in SUPPORTED_TIMEFRAMES:
        return _finish(
            started,
            _fail(
                "INVALID_ARGUMENT",
                error="UNSUPPORTED_TIMEFRAME",
                supported_timeframes=list(SUPPORTED_TIMEFRAMES),
            ),
        )
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        return _finish(
            started,
            _fail("INVALID_ARGUMENT", error="INVALID_LIMIT", limit_max=500),
        )
    if snapshot_max_age_seconds <= 0:
        raise ValueError("snapshot_max_age_seconds must be positive")

    source_path = path or os.environ.get(
        "STOCK_RAZOR_CN_EASTMONEY_STATUS_PATH",
        DEFAULT_STATUS_PATH,
    )
    payload, error = _load(source_path)
    if payload is None:
        return _finish(
            started,
            _fail("UNAVAILABLE", error=error, source_path=source_path),
        )

    if payload.get("schema") != "stock_razor_cn_eastmoney_observation_v1":
        return _finish(
            started,
            _fail("INVALID", error="UNSUPPORTED_SCHEMA", source_path=source_path),
        )

    if not (
        payload.get("intraday_timestamp_semantics_proven") is False
        and payload.get("intraday_currentness_proven") is False
        and payload.get("research_only") is True
        and payload.get("can_confirm_signal") is False
        and payload.get("radar_admission") == "BLOCKED"
        and payload.get("live_trade") is False
    ):
        return _finish(
            started,
            _fail("INVALID", error="SAFETY_CONTRACT_VIOLATION", source_path=source_path),
        )

    emitted_at = _timestamp(payload.get("emitted_at_utc"))
    if emitted_at is None:
        return _finish(started, _fail("INVALID", error="INVALID_EMITTED_AT"))
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    age_seconds = (now.astimezone(timezone.utc) - emitted_at).total_seconds()
    if age_seconds < -5:
        return _finish(started, _fail("INVALID", error="FUTURE_EMITTED_AT"))

    symbols = payload.get("symbols")
    symbols = symbols if isinstance(symbols, dict) else {}
    item = symbols.get(code)
    if not isinstance(item, dict):
        return _finish(
            started,
            _fail(
                "NOT_FOUND",
                error="SYMBOL_NOT_OBSERVED",
                symbol=code,
                source_age_seconds=age_seconds,
            ),
        )

    frames = item.get("timeframes")
    frames = frames if isinstance(frames, dict) else {}
    frame_payload = frames.get(frame)
    if not isinstance(frame_payload, dict):
        return _finish(
            started,
            _fail("INVALID", error="TIMEFRAME_PAYLOAD_MISSING", symbol=code),
        )

    rows = frame_payload.get("rows")
    rows = rows if isinstance(rows, list) else []
    selected = rows[-limit:]
    snapshot_status = "PASS" if age_seconds <= snapshot_max_age_seconds else "STALE"

    return _finish(started, {
        "ok": True,
        "status": snapshot_status,
        "symbol": code,
        "timeframe": frame,
        "rows": selected,
        "returned_row_count": len(selected),
        "total_row_count": len(rows),
        "provider_policy": payload.get("provider_policy"),
        "provider_used": frame_payload.get("provider_used"),
        "provider_lineage": frame_payload.get("provider_lineage"),
        "fallback_from": frame_payload.get("fallback_from"),
        "fallback_reason": frame_payload.get("fallback_reason"),
        "timestamp_semantic": frame_payload.get("timestamp_semantic"),
        "currentness": frame_payload.get("currentness"),
        "snapshot_repo_sha": payload.get("repo_sha"),
        "runtime_instance_id": payload.get("runtime_instance_id"),
        "sequence": payload.get("sequence"),
        "emitted_at_utc": payload.get("emitted_at_utc"),
        "source_age_seconds": age_seconds,
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    })

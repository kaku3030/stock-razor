"""Fast fail-closed reader for the cloud A-share observation state."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from threading import RLock
from time import perf_counter

from src.services.a_share_intraday_currentness import (
    qualify_same_session_currentness,
)
from src.services.a_share_intraday_semantics import TimestampSemantic


DEFAULT_STATUS_PATH = "/run/stock-razor-cn-eastmoney/latest-observation.json"
DEFAULT_MAX_AGE_SECONDS = 180
SUPPORTED_TIMEFRAMES = ("1d", "60m", "15m")

_CACHE_LOCK = RLock()
_CACHE: dict[str, tuple[tuple[int, int, int, int], dict]] = {}


def _finish(started_at: float, payload: dict) -> dict:
    return {
        **payload,
        "read_latency_ms": round((perf_counter() - started_at) * 1000, 3),
    }


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


def _signature(path: str) -> tuple[int, int, int, int]:
    stat = os.stat(path)
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)


def _load(path: str) -> tuple[dict | None, str | None, bool]:
    try:
        signature = _signature(path)
    except OSError as exc:
        return None, type(exc).__name__, False

    with _CACHE_LOCK:
        cached = _CACHE.get(path)
        if cached is not None and cached[0] == signature:
            return cached[1], None, True

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
            stat = os.fstat(handle.fileno())
            loaded_signature = (
                stat.st_dev,
                stat.st_ino,
                stat.st_mtime_ns,
                stat.st_size,
            )
    except (OSError, ValueError, TypeError) as exc:
        return None, type(exc).__name__, False
    if not isinstance(payload, dict):
        return None, "INVALID_JSON_ROOT", False

    with _CACHE_LOCK:
        _CACHE[path] = (loaded_signature, payload)
    return payload, None, False


def _aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _symbol(value: object) -> str | None:
    raw = str(value or "").strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if raw.endswith(suffix):
            raw = raw[:-3]
            break
    for prefix in ("SH", "SZ", "BJ"):
        if raw.startswith(prefix) and len(raw) == 8:
            raw = raw[2:]
            break
    if len(raw) != 6 or not raw.isdigit():
        return None
    return raw


def _validate_symbol_currentness(
    item: dict,
    *,
    observed_at: datetime,
) -> tuple[bool | None, str | None]:
    claim = item.get("intraday_currentness_proven")
    if not isinstance(claim, bool):
        return None, "SYMBOL_CURRENTNESS_INVALID"
    frames = item.get("timeframes")
    if not isinstance(frames, dict):
        return None, "SYMBOL_TIMEFRAMES_INVALID"

    proven: list[bool] = []
    for timeframe in ("60m", "15m"):
        frame = frames.get(timeframe)
        if not isinstance(frame, dict):
            return None, "CURRENTNESS_FRAME_MISSING"
        currentness = frame.get("currentness")
        if currentness not in {"UNPROVEN", "PROVEN"}:
            return None, "CURRENTNESS_CLAIM_INVALID"
        if frame.get("timestamp_semantic") != "BAR_END":
            if currentness != "UNPROVEN":
                return None, "CURRENTNESS_WITHOUT_BAR_END"
            proven.append(False)
            continue

        evidence = frame.get("currentness_qualification")
        if evidence is None:
            if currentness != "UNPROVEN":
                return None, "CURRENTNESS_EVIDENCE_MISSING"
            proven.append(False)
            continue
        if not isinstance(evidence, dict):
            return None, "CURRENTNESS_EVIDENCE_INVALID"
        rows = frame.get("rows")
        if not isinstance(rows, list) or not rows or not isinstance(rows[-1], dict):
            return None, "CURRENTNESS_ROWS_INVALID"
        expected = qualify_same_session_currentness(
            str(rows[-1].get("label") or ""),
            interval_minutes=int(timeframe[:-1]),
            timestamp_semantic=TimestampSemantic.BAR_END,
            observed_at=observed_at,
        )
        if evidence != expected.to_dict():
            return None, "CURRENTNESS_EVIDENCE_MISMATCH"
        frame_proven = expected.currentness_proven
        if (currentness == "PROVEN") is not frame_proven:
            return None, "CURRENTNESS_CLAIM_EVIDENCE_MISMATCH"
        proven.append(frame_proven)

    evaluated = all(proven)
    if claim is not evaluated:
        return None, "SYMBOL_CURRENTNESS_MISMATCH"
    return evaluated, None


def read_cn_market_data(
    symbol: object,
    timeframe: str = "1d",
    limit: int = 120,
    *,
    path: str | None = None,
    now_utc: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> dict:
    """Return bounded cloud A-share rows without provider I/O or recomputation."""

    started_at = perf_counter()
    normalized = _symbol(symbol)
    if normalized is None:
        return _finish(started_at, _fail("INVALID_ARGUMENT", error="INVALID_SYMBOL"))

    frame = str(timeframe or "").strip().lower()
    if frame not in SUPPORTED_TIMEFRAMES:
        return _finish(
            started_at,
            _fail(
                "INVALID_ARGUMENT",
                error="UNSUPPORTED_TIMEFRAME",
                supported_timeframes=list(SUPPORTED_TIMEFRAMES),
            ),
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        return _finish(
            started_at,
            _fail("INVALID_ARGUMENT", error="INVALID_LIMIT", limit_max=500),
        )
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    source_path = path or os.environ.get(
        "STOCK_RAZOR_CN_EASTMONEY_STATUS_PATH",
        DEFAULT_STATUS_PATH,
    )
    payload, error, cache_hit = _load(source_path)
    if payload is None:
        return _finish(
            started_at,
            _fail(
                "UNAVAILABLE",
                error=error,
                source_path=source_path,
                source_cache_hit=False,
            ),
        )

    if payload.get("schema") != "stock_razor_cn_eastmoney_observation_v1":
        return _finish(
            started_at,
            _fail("INVALID", error="UNSUPPORTED_SCHEMA", source_path=source_path),
        )
    intraday_timestamp_semantics_proven = payload.get(
        "intraday_timestamp_semantics_proven"
    )
    intraday_currentness_proven = payload.get("intraday_currentness_proven")
    if not (
        isinstance(intraday_timestamp_semantics_proven, bool)
        and isinstance(intraday_currentness_proven, bool)
        and payload.get("research_only") is True
        and payload.get("can_confirm_signal") is False
        and payload.get("radar_admission") == "BLOCKED"
        and payload.get("live_trade") is False
    ):
        return _finish(
            started_at,
            _fail(
                "INVALID",
                error="SAFETY_CONTRACT_VIOLATION",
                source_path=source_path,
            ),
        )

    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    emitted = _aware_timestamp(payload.get("emitted_at_utc"))
    if emitted is None:
        return _finish(
            started_at,
            _fail("INVALID", error="INVALID_EMITTED_AT", source_path=source_path),
        )
    age = (now.astimezone(timezone.utc) - emitted).total_seconds()
    if age < -5:
        return _finish(
            started_at,
            _fail("INVALID", error="FUTURE_EMITTED_AT", source_path=source_path),
        )

    symbols = payload.get("symbols")
    symbols = symbols if isinstance(symbols, dict) else {}
    item = symbols.get(normalized)
    if not isinstance(item, dict):
        return _finish(started_at, {
            **_fail("NO_DATA"),
            "source_path": source_path,
            "source_age_seconds": age,
            "source_cache_hit": cache_hit,
            "symbol": normalized,
            "timeframe": frame,
            "rows": [],
            "row_count": 0,
        })
    if not (
        item.get("radar_admission") == "BLOCKED"
        and item.get("live_trade") is False
    ):
        return _finish(
            started_at,
            _fail("INVALID", error="SYMBOL_SAFETY_CONTRACT_VIOLATION"),
        )

    frames = item.get("timeframes")
    frames = frames if isinstance(frames, dict) else {}
    frame_payload = frames.get(frame)
    if not isinstance(frame_payload, dict):
        return _finish(started_at, {
            **_fail("NO_DATA"),
            "symbol": normalized,
            "timeframe": frame,
            "rows": [],
            "row_count": 0,
        })
    symbol_timestamp_semantics_proven = item.get(
        "intraday_timestamp_semantics_proven"
    )
    if symbol_timestamp_semantics_proven not in {True, False, None}:
        return _finish(
            started_at,
            _fail("INVALID", error="SYMBOL_TIMESTAMP_SEMANTICS_INVALID"),
        )
    if frame in {"15m", "60m"} and frame_payload.get("timestamp_semantic") == "BAR_END":
        qualification = frame_payload.get("timestamp_qualification")
        if not (
            isinstance(qualification, dict)
            and qualification.get("status") == "PASS"
            and qualification.get("timestamp_semantic") == "BAR_END"
            and qualification.get("currentness_proven") is False
            and qualification.get("radar_admission") == "BLOCKED"
            and qualification.get("live_trade") is False
        ):
            return _finish(
                started_at,
                _fail("INVALID", error="TIMESTAMP_SEMANTICS_EVIDENCE_INVALID"),
            )
    if (
        symbol_timestamp_semantics_proven is True
        and frame in {"15m", "60m"}
        and frame_payload.get("timestamp_semantic") != "BAR_END"
    ):
        return _finish(
            started_at,
            _fail("INVALID", error="SYMBOL_TIMESTAMP_SEMANTICS_MISMATCH"),
        )

    symbol_currentness_proven, currentness_error = _validate_symbol_currentness(
        item,
        observed_at=emitted,
    )
    if currentness_error is not None:
        return _finish(
            started_at,
            _fail("INVALID", error=currentness_error),
        )
    if intraday_currentness_proven and symbol_currentness_proven is not True:
        return _finish(
            started_at,
            _fail("INVALID", error="ROOT_CURRENTNESS_MISMATCH"),
        )

    provider_request_latency_ms = frame_payload.get("request_latency_ms")
    if (
        provider_request_latency_ms is not None
        and (
            isinstance(provider_request_latency_ms, bool)
            or not isinstance(provider_request_latency_ms, (int, float))
            or provider_request_latency_ms < 0
        )
    ):
        return _finish(
            started_at,
            _fail("INVALID", error="PROVIDER_REQUEST_LATENCY_INVALID"),
        )
    rows = frame_payload.get("rows")
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    selected = rows[-limit:]
    source_status = "PASS" if age <= max_age_seconds else "STALE"
    return _finish(started_at, {
        "ok": bool(selected),
        "status": source_status if selected else "NO_DATA",
        "source_path": source_path,
        "source_age_seconds": age,
        "source_cache_hit": cache_hit,
        "repo_sha": payload.get("repo_sha"),
        "runtime_instance_id": payload.get("runtime_instance_id"),
        "sequence": payload.get("sequence"),
        "emitted_at_utc": payload.get("emitted_at_utc"),
        "provider_policy": payload.get("provider_policy"),
        "provider_lineages": payload.get("provider_lineages"),
        "intraday_timestamp_semantics_proven": intraday_timestamp_semantics_proven,
        "intraday_currentness_proven": intraday_currentness_proven,
        "symbol_intraday_timestamp_semantics_proven": (
            symbol_timestamp_semantics_proven is True
        ),
        "symbol_intraday_currentness_proven": symbol_currentness_proven is True,
        "symbol": normalized,
        "symbol_status": item.get("status"),
        "timeframe": frame,
        "provider_used": frame_payload.get("provider_used"),
        "provider_lineage": frame_payload.get("provider_lineage"),
        "provider_request_latency_ms": (
            float(provider_request_latency_ms)
            if provider_request_latency_ms is not None
            else None
        ),
        "fallback_from": frame_payload.get("fallback_from"),
        "fallback_reason": frame_payload.get("fallback_reason"),
        "timestamp_semantic": frame_payload.get("timestamp_semantic"),
        "timestamp_qualification": frame_payload.get("timestamp_qualification"),
        "currentness_qualification": frame_payload.get("currentness_qualification"),
        "currentness": frame_payload.get("currentness"),
        "total_row_count": len(rows),
        "row_count": len(selected),
        "rows": selected,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    })

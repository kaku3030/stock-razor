"""Fast fail-closed reader for the isolated A-share cloud Radar state."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from threading import RLock
from time import perf_counter
from typing import Iterable


DEFAULT_STATUS_PATH = "/run/stock-razor-cn-radar/latest-research-state.json"
DEFAULT_MAX_AGE_SECONDS = 180

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


def _aware(value: object) -> datetime | None:
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


def _symbols(values: Iterable[object] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if values is None:
        return (), ()
    normalized: list[str] = []
    invalid: list[str] = []
    for value in values:
        symbol = _symbol(value)
        if symbol is None:
            invalid.append(str(value))
        elif symbol not in normalized:
            normalized.append(symbol)
    return tuple(normalized), tuple(invalid)


def read_cn_radar_analysis(
    symbols: Iterable[object] | None = None,
    *,
    path: str | None = None,
    now_utc: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> dict:
    """Return precomputed A-share Radar research state without recomputation."""

    started_at = perf_counter()
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    source_path = path or os.environ.get(
        "STOCK_RAZOR_CN_RADAR_STATUS_PATH",
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
    if payload.get("type") != "cn_radar_research_heartbeat":
        return _finish(
            started_at,
            _fail("INVALID", error="UNSUPPORTED_SCHEMA", source_path=source_path),
        )
    if not (
        payload.get("research_only") is True
        and payload.get("can_confirm_signal") is False
        and payload.get("radar_admission") == "BLOCKED"
        and payload.get("live_trade") is False
    ):
        return _finish(
            started_at,
            _fail("INVALID", error="SAFETY_CONTRACT_VIOLATION"),
        )

    evaluation = payload.get("evaluation")
    if not isinstance(evaluation, dict):
        return _finish(
            started_at,
            _fail("INVALID", error="MISSING_EVALUATION"),
        )
    evaluation_timestamp_semantics_proven = evaluation.get(
        "intraday_timestamp_semantics_proven"
    )
    evaluation_currentness_proven = evaluation.get(
        "intraday_currentness_proven"
    )
    if not (
        evaluation.get("schema") == "stock_razor_cn_radar_research_v1"
        and isinstance(evaluation_timestamp_semantics_proven, bool)
        and isinstance(evaluation_currentness_proven, bool)
        and evaluation.get("research_only") is True
        and evaluation.get("can_confirm_signal") is False
        and evaluation.get("radar_admission") == "BLOCKED"
        and evaluation.get("live_trade") is False
    ):
        return _finish(
            started_at,
            _fail("INVALID", error="EVALUATION_SAFETY_CONTRACT_VIOLATION"),
        )

    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    emitted = _aware(payload.get("emitted_at_utc"))
    if emitted is None:
        return _finish(
            started_at,
            _fail("INVALID", error="INVALID_EMITTED_AT"),
        )
    age = (now.astimezone(timezone.utc) - emitted).total_seconds()
    if age < -5:
        return _finish(
            started_at,
            _fail("INVALID", error="FUTURE_EMITTED_AT"),
        )

    requested, invalid = _symbols(symbols)
    if invalid:
        return _finish(
            started_at,
            _fail(
                "INVALID_ARGUMENT",
                error="INVALID_SYMBOL",
                invalid_symbols=list(invalid),
            ),
        )

    raw_symbols = evaluation.get("symbols")
    raw_symbols = raw_symbols if isinstance(raw_symbols, dict) else {}
    research_states = [
        item
        for item in raw_symbols.values()
        if isinstance(item, dict) and item.get("status") == "RESEARCH_STATE"
    ]
    if any(
        not (
            isinstance(item.get("intraday_currentness_proven"), bool)
            and item.get("research_only") is True
            and item.get("can_confirm_signal") is False
            and item.get("signal_permission") == "record_only"
        )
        for item in research_states
    ):
        return _finish(
            started_at,
            _fail("INVALID", error="RESEARCH_STATE_SAFETY_CONTRACT_VIOLATION"),
        )
    if evaluation_currentness_proven and (
        not research_states
        or len(research_states) != len(raw_symbols)
        or not all(
            item.get("intraday_currentness_proven") is True
            for item in research_states
        )
    ):
        return _finish(
            started_at,
            _fail("INVALID", error="EVALUATION_CURRENTNESS_MISMATCH"),
        )
    selected = requested or tuple(sorted(raw_symbols))
    result = {
        symbol: raw_symbols[symbol]
        for symbol in selected
        if isinstance(raw_symbols.get(symbol), dict)
    }
    missing = [symbol for symbol in selected if symbol not in result]

    source_status = "PASS" if age <= max_age_seconds else "STALE"
    return _finish(started_at, {
        "ok": True,
        "status": source_status,
        "source_path": source_path,
        "source_age_seconds": age,
        "source_cache_hit": cache_hit,
        "worker_repo_sha": payload.get("worker_repo_sha"),
        "runtime_instance_id": payload.get("runtime_instance_id"),
        "sequence": payload.get("sequence"),
        "emitted_at_utc": payload.get("emitted_at_utc"),
        "poll_status": payload.get("poll_status"),
        "source_repo_sha": payload.get("source_repo_sha"),
        "source_runtime_instance_id": payload.get("source_runtime_instance_id"),
        "source_sequence": payload.get("source_sequence"),
        "source_emitted_at_utc": payload.get("source_emitted_at_utc"),
        "source_age_seconds_reported": payload.get("source_age_seconds"),
        "evaluation_status": evaluation.get("status"),
        "research_state_symbols": evaluation.get("research_state_symbols") or [],
        "provider_policy": evaluation.get("provider_policy"),
        "provider_lineages": evaluation.get("provider_lineages") or [],
        "intraday_timestamp_semantics_proven": evaluation_timestamp_semantics_proven,
        "intraday_currentness_proven": evaluation_currentness_proven,
        "symbols": result,
        "missing_symbols": missing,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    })

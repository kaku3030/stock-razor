"""Fast fail-closed reader for the cloud A-share Radar research state."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from time import perf_counter
from typing import Iterable


DEFAULT_STATUS_PATH = "/run/stock-razor-cn-radar/latest-research-state.json"
DEFAULT_MAX_AGE_SECONDS = 30


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


def _load(path: str) -> tuple[dict | None, str | None]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError) as exc:
        return None, type(exc).__name__
    if not isinstance(payload, dict):
        return None, "INVALID_JSON_ROOT"
    return payload, None


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


def _normalize_symbol(value: object) -> str | None:
    symbol = str(value or "").strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if symbol.endswith(suffix):
            symbol = symbol[:-3]
            break
    for prefix in ("SH", "SZ", "BJ"):
        if symbol.startswith(prefix) and len(symbol) == 8:
            symbol = symbol[2:]
            break
    if len(symbol) != 6 or not symbol.isdigit():
        return None
    return symbol


def _normalize_symbols(values: Iterable[object] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if values is None:
        return (), ()
    normalized: list[str] = []
    invalid: list[str] = []
    for value in values:
        symbol = _normalize_symbol(value)
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
    """Return the latest precomputed A-share Radar research state."""

    started_at = perf_counter()
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    source_path = path or os.environ.get(
        "STOCK_RAZOR_CN_RADAR_STATUS_PATH",
        DEFAULT_STATUS_PATH,
    )
    payload, error = _load(source_path)
    if payload is None:
        return _finish(
            started_at,
            _fail("UNAVAILABLE", error=error, source_path=source_path),
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
            _fail(
                "INVALID",
                error="SAFETY_CONTRACT_VIOLATION",
                source_path=source_path,
            ),
        )

    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    emitted_at = _aware_timestamp(payload.get("emitted_at_utc"))
    if emitted_at is None:
        return _finish(
            started_at,
            _fail("INVALID", error="INVALID_EMITTED_AT", source_path=source_path),
        )
    age_seconds = (now.astimezone(timezone.utc) - emitted_at).total_seconds()
    if age_seconds < -5:
        return _finish(
            started_at,
            _fail("INVALID", error="FUTURE_EMITTED_AT", source_path=source_path),
        )

    evaluation = payload.get("evaluation")
    if not isinstance(evaluation, dict):
        return _finish(
            started_at,
            _fail("INVALID", error="MISSING_EVALUATION", source_path=source_path),
        )
    if not (
        evaluation.get("schema") == "stock_razor_cn_radar_research_v1"
        and evaluation.get("research_only") is True
        and evaluation.get("can_confirm_signal") is False
        and evaluation.get("radar_admission") == "BLOCKED"
        and evaluation.get("live_trade") is False
        and evaluation.get("intraday_timestamp_semantics_proven") is False
        and evaluation.get("intraday_currentness_proven") is False
    ):
        return _finish(
            started_at,
            _fail(
                "INVALID",
                error="EVALUATION_SAFETY_CONTRACT_VIOLATION",
                source_path=source_path,
            ),
        )

    requested, invalid = _normalize_symbols(symbols)
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
    by_symbol = {
        str(symbol).strip().upper(): item
        for symbol, item in raw_symbols.items()
        if isinstance(item, dict)
    }
    selected = requested or tuple(sorted(by_symbol))
    result = {symbol: by_symbol[symbol] for symbol in selected if symbol in by_symbol}
    missing = [symbol for symbol in selected if symbol not in by_symbol]

    source_status = "PASS" if age_seconds <= max_age_seconds else "STALE"
    return _finish(started_at, {
        "ok": True,
        "status": source_status,
        "source_path": source_path,
        "source_age_seconds": age_seconds,
        "worker_repo_sha": payload.get("worker_repo_sha"),
        "runtime_instance_id": payload.get("runtime_instance_id"),
        "sequence": payload.get("sequence"),
        "emitted_at_utc": payload.get("emitted_at_utc"),
        "poll_status": payload.get("poll_status"),
        "source_repo_sha": payload.get("source_repo_sha"),
        "source_runtime_instance_id": payload.get("source_runtime_instance_id"),
        "source_sequence": payload.get("source_sequence"),
        "source_emitted_at_utc": payload.get("source_emitted_at_utc"),
        "provider_policy": evaluation.get("provider_policy"),
        "provider_lineages": evaluation.get("provider_lineages") or [],
        "research_state_symbols": evaluation.get("research_state_symbols") or [],
        "symbols": result,
        "missing_symbols": missing,
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    })

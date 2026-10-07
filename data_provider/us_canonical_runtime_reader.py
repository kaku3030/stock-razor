"""Fast fail-closed readers for the canonical US livefeed runtime."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Iterable


DEFAULT_STATUS_PATH = "/run/stock-razor-us-livefeed/latest-heartbeat.json"
DEFAULT_SNAPSHOT_PATH = "/run/stock-razor-us-livefeed/canonical-market-snapshot.json"
DEFAULT_HEARTBEAT_MAX_AGE_SECONDS = 30
DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = 120
SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "1h")


def _fail(status: str, *, error: str | None = None, **extra) -> dict:
    payload = {
        "ok": False,
        "status": status,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    if error is not None:
        payload["error"] = error
    payload.update(extra)
    return payload


def _load_json(path: str) -> tuple[dict | None, str | None]:
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


def _age_seconds(value: object, *, now_utc: datetime) -> float | None:
    emitted = _aware_timestamp(value)
    if emitted is None:
        return None
    return (now_utc.astimezone(timezone.utc) - emitted).total_seconds()


def _now(now_utc: datetime | None) -> datetime:
    value = now_utc or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    return value.astimezone(timezone.utc)


def _safety_contract(payload: dict) -> bool:
    return (
        payload.get("radar_admission") == "BLOCKED"
        and payload.get("live_trade") is False
    )


def _snapshot_path(path: str | None) -> str:
    return path or os.environ.get(
        "STOCK_RAZOR_US_CANONICAL_SNAPSHOT_PATH",
        DEFAULT_SNAPSHOT_PATH,
    )


def _status_path(path: str | None) -> str:
    return path or os.environ.get(
        "STOCK_RAZOR_US_LIVEFEED_STATUS_PATH",
        DEFAULT_STATUS_PATH,
    )


def _normalize_symbol(value: object) -> str | None:
    symbol = str(value or "").strip().upper()
    if not symbol:
        return None
    if "." not in symbol:
        symbol = "US." + symbol
    if not symbol.startswith("US."):
        return None
    tail = symbol[3:]
    if not tail or any(ch.isspace() for ch in tail):
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


def _snapshot_source(
    path: str | None,
    *,
    now_utc: datetime | None,
    max_age_seconds: int,
) -> tuple[dict | None, dict]:
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    source_path = _snapshot_path(path)
    payload, error = _load_json(source_path)
    if payload is None:
        return None, _fail("UNAVAILABLE", error=error, source_path=source_path)
    if payload.get("schema") != "stock_razor_canonical_market_snapshot_v1":
        return None, _fail("INVALID", error="UNSUPPORTED_SCHEMA", source_path=source_path)
    if not _safety_contract(payload):
        return None, _fail(
            "INVALID",
            error="SAFETY_CONTRACT_VIOLATION",
            source_path=source_path,
        )
    now = _now(now_utc)
    age = _age_seconds(payload.get("emitted_at_utc"), now_utc=now)
    if age is None or age < -5:
        return None, _fail(
            "INVALID",
            error="INVALID_EMITTED_AT",
            source_path=source_path,
        )
    source_status = "PASS" if age <= max_age_seconds else "STALE"
    meta = {
        "ok": True,
        "status": source_status,
        "source_path": source_path,
        "source_age_seconds": age,
        "repo_sha": payload.get("repo_sha"),
        "runtime_instance_id": payload.get("runtime_instance_id"),
        "sequence": payload.get("sequence"),
        "emitted_at_utc": payload.get("emitted_at_utc"),
        "market_state_us": payload.get("market_state_us"),
        "cache_session_us": payload.get("cache_session_us"),
        "delivery_mode": payload.get("delivery_mode"),
        "bar_closure": payload.get("bar_closure"),
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    return payload, meta


def read_us_livefeed_health(
    status_path: str | None = None,
    snapshot_path: str | None = None,
    *,
    now_utc: datetime | None = None,
    heartbeat_max_age_seconds: int = DEFAULT_HEARTBEAT_MAX_AGE_SECONDS,
    snapshot_max_age_seconds: int = DEFAULT_SNAPSHOT_MAX_AGE_SECONDS,
) -> dict:
    """Return compact service health without touching a provider SDK."""

    if heartbeat_max_age_seconds <= 0:
        raise ValueError("heartbeat_max_age_seconds must be positive")
    now = _now(now_utc)
    source_path = _status_path(status_path)
    heartbeat, error = _load_json(source_path)
    if heartbeat is None:
        return _fail("UNAVAILABLE", error=error, source_path=source_path)
    if heartbeat.get("type") != "us_opend_livefeed_heartbeat":
        return _fail("INVALID", error="UNSUPPORTED_HEARTBEAT", source_path=source_path)
    if not _safety_contract(heartbeat):
        return _fail(
            "INVALID",
            error="SAFETY_CONTRACT_VIOLATION",
            source_path=source_path,
        )

    age = _age_seconds(heartbeat.get("emitted_at_utc"), now_utc=now)
    if age is None or age < -5:
        return _fail("INVALID", error="INVALID_EMITTED_AT", source_path=source_path)
    heartbeat_fresh = age <= heartbeat_max_age_seconds
    controller_connected = heartbeat.get("controller_lifecycle") == "CONNECTED"
    canonical_export = heartbeat.get("canonical_snapshot_export")
    canonical_export = canonical_export if isinstance(canonical_export, dict) else {}
    export_pass = canonical_export.get("status") == "PASS"

    snapshot, snapshot_meta = _snapshot_source(
        snapshot_path,
        now_utc=now,
        max_age_seconds=snapshot_max_age_seconds,
    )
    symbols = heartbeat.get("canonical_cache")
    symbols = symbols if isinstance(symbols, dict) else {}
    cache_counts = {
        str(symbol): {
            "1m": int(item.get("bar_count") or 0),
            "5m": int(item.get("bar_count_5m") or 0),
            "15m": int(item.get("bar_count_15m") or 0),
            "1h": int(item.get("bar_count_1h") or 0),
        }
        for symbol, item in symbols.items()
        if isinstance(item, dict)
    }
    healthy = heartbeat_fresh and controller_connected and export_pass
    status = "HEALTHY" if healthy else ("STALE" if not heartbeat_fresh else "DEGRADED")
    return {
        "ok": healthy,
        "status": status,
        "heartbeat_age_seconds": age,
        "repo_sha": heartbeat.get("repo_sha"),
        "runtime_instance_id": heartbeat.get("runtime_instance_id"),
        "sequence": heartbeat.get("sequence"),
        "emitted_at_utc": heartbeat.get("emitted_at_utc"),
        "controller_lifecycle": heartbeat.get("controller_lifecycle"),
        "market_state_us": heartbeat.get("market_state_us"),
        "cache_session_us": heartbeat.get("cache_session_us"),
        "delivery_mode": heartbeat.get("delivery_mode"),
        "bar_closure": heartbeat.get("bar_closure"),
        "last_push_utc": heartbeat.get("last_push_utc"),
        "event_count": heartbeat.get("event_count"),
        "accepted_event_count": heartbeat.get("accepted_event_count"),
        "quote_right_evidence": heartbeat.get("quote_right_evidence"),
        "canonical_export_status": canonical_export.get("status"),
        "canonical_snapshot_status": snapshot_meta.get("status"),
        "canonical_snapshot_age_seconds": snapshot_meta.get("source_age_seconds"),
        "canonical_snapshot_available": snapshot is not None,
        "cache_counts": cache_counts,
        "realtime_delivery_evidence": (
            heartbeat_fresh and heartbeat.get("delivery_mode") == "REALTIME"
        ),
        "bar_closure_proven": heartbeat.get("bar_closure") == "PROVEN",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def read_us_market_snapshots(
    symbols: Iterable[object] | None = None,
    *,
    path: str | None = None,
    now_utc: datetime | None = None,
    max_age_seconds: int = DEFAULT_SNAPSHOT_MAX_AGE_SECONDS,
) -> dict:
    """Return compact latest canonical bars for requested US symbols."""

    payload, meta = _snapshot_source(
        path,
        now_utc=now_utc,
        max_age_seconds=max_age_seconds,
    )
    if payload is None:
        return meta

    source_symbols = payload.get("symbols")
    if not isinstance(source_symbols, dict):
        return _fail("INVALID", error="INVALID_SYMBOL_MAP", **{
            key: value for key, value in meta.items()
            if key not in {"ok", "status", "radar_admission", "live_trade"}
        })

    requested, invalid = _normalize_symbols(symbols)
    if invalid:
        return _fail(
            "INVALID_ARGUMENT",
            error="INVALID_SYMBOL",
            invalid_symbols=list(invalid),
        )
    selected = requested or tuple(sorted(source_symbols))
    result: dict[str, dict] = {}
    missing: list[str] = []
    for symbol in selected:
        item = source_symbols.get(symbol)
        if not isinstance(item, dict):
            missing.append(symbol)
            continue
        frames = item.get("timeframes")
        frames = frames if isinstance(frames, dict) else {}
        latest = {}
        counts = {}
        for timeframe in SUPPORTED_TIMEFRAMES:
            bars = frames.get(timeframe)
            bars = bars if isinstance(bars, list) else []
            counts[timeframe] = len(bars)
            latest[timeframe] = bars[-1] if bars and isinstance(bars[-1], dict) else None
        result[symbol] = {
            "health": item.get("health"),
            "provider": item.get("provider"),
            "feed": item.get("feed"),
            "counts": counts,
            "latest": latest,
        }

    return {
        **meta,
        "symbols": result,
        "missing_symbols": missing,
        "data_available": any(
            any(value is not None for value in item["latest"].values())
            for item in result.values()
        ),
    }


def read_us_market_bars(
    symbol: object,
    timeframe: str = "15m",
    limit: int = 100,
    *,
    path: str | None = None,
    now_utc: datetime | None = None,
    max_age_seconds: int = DEFAULT_SNAPSHOT_MAX_AGE_SECONDS,
) -> dict:
    """Return bounded canonical bars from the local cloud snapshot."""

    normalized = _normalize_symbol(symbol)
    if normalized is None:
        return _fail("INVALID_ARGUMENT", error="INVALID_SYMBOL")
    frame = str(timeframe or "").strip().lower()
    if frame not in SUPPORTED_TIMEFRAMES:
        return _fail(
            "INVALID_ARGUMENT",
            error="UNSUPPORTED_TIMEFRAME",
            supported_timeframes=list(SUPPORTED_TIMEFRAMES),
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 480:
        return _fail("INVALID_ARGUMENT", error="INVALID_LIMIT", limit_max=480)

    payload, meta = _snapshot_source(
        path,
        now_utc=now_utc,
        max_age_seconds=max_age_seconds,
    )
    if payload is None:
        return meta
    source_symbols = payload.get("symbols")
    source_symbols = source_symbols if isinstance(source_symbols, dict) else {}
    item = source_symbols.get(normalized)
    if not isinstance(item, dict):
        return {
            **meta,
            "ok": False,
            "status": "NO_DATA",
            "symbol": normalized,
            "timeframe": frame,
            "bars": [],
            "bar_count": 0,
            "total_bar_count": 0,
        }
    frames = item.get("timeframes")
    frames = frames if isinstance(frames, dict) else {}
    bars = frames.get(frame)
    bars = [bar for bar in bars if isinstance(bar, dict)] if isinstance(bars, list) else []
    selected = bars[-limit:]
    return {
        **meta,
        "ok": bool(selected),
        "status": meta["status"] if selected else "NO_DATA",
        "symbol": normalized,
        "timeframe": frame,
        "bar_count": len(selected),
        "total_bar_count": len(bars),
        "bars": selected,
    }

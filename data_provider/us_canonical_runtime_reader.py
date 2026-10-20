"""Fast fail-closed readers for the canonical US livefeed runtime."""

from __future__ import annotations

from math import isfinite

from datetime import datetime, timezone
import json
import os
from threading import RLock
from time import perf_counter
from typing import Iterable
from zoneinfo import ZoneInfo


DEFAULT_STATUS_PATH = "/run/stock-razor-us-livefeed/latest-heartbeat.json"
DEFAULT_SNAPSHOT_PATH = "/run/stock-razor-us-livefeed/canonical-market-snapshot.json"
DEFAULT_HEARTBEAT_MAX_AGE_SECONDS = 30
DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = 120
SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "1h")

_JSON_CACHE_LOCK = RLock()
_JSON_CACHE: dict[str, tuple[tuple[int, int, int, int], dict]] = {}


def _latency_payload(started_at: float, payload: dict) -> dict:
    return {
        **payload,
        "read_latency_ms": round((perf_counter() - started_at) * 1000, 3),
    }


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


def _file_signature(path: str) -> tuple[int, int, int, int]:
    stat = os.stat(path)
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)


def _load_json(path: str) -> tuple[dict | None, str | None, bool]:
    try:
        signature = _file_signature(path)
    except OSError as exc:
        return None, type(exc).__name__, False

    with _JSON_CACHE_LOCK:
        cached = _JSON_CACHE.get(path)
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

    with _JSON_CACHE_LOCK:
        _JSON_CACHE[path] = (loaded_signature, payload)
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


def _qualified_latest_push_observations(
    raw: object,
    *,
    allowed_symbols: object,
    now_utc: datetime,
    fresh_seconds: int = 90,
) -> dict[str, dict]:
    """Return bounded, validated forming K1M observations, never closed bars."""

    if not isinstance(raw, dict) or len(raw) > 20:
        return {}
    allowed = set()
    if isinstance(allowed_symbols, list) and len(allowed_symbols) <= 200:
        allowed = {
            symbol for value in allowed_symbols
            if (symbol := _normalize_symbol(value)) is not None
        }
    result: dict[str, dict] = {}
    for raw_symbol, item in raw.items():
        symbol = _normalize_symbol(raw_symbol)
        if symbol is None or symbol not in allowed or not isinstance(item, dict):
            continue
        if item.get("symbol") != symbol:
            continue
        time_key = item.get("time_key")
        if not isinstance(time_key, str) or not 1 <= len(time_key) <= 32:
            continue
        received_at = _aware_timestamp(item.get("received_at_utc"))
        if received_at is None:
            continue
        age_seconds = (now_utc - received_at).total_seconds()
        if age_seconds < -5:
            continue
        values: dict[str, float] = {}
        valid = True
        for field in ("open", "high", "low", "close", "volume"):
            value = item.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(value)
            ):
                valid = False
                break
            values[field] = float(value)
        if not valid:
            continue
        open_, high, low, close, volume = (
            values[name] for name in ("open", "high", "low", "close", "volume")
        )
        if (
            min(open_, high, low, close) <= 0
            or volume < 0
            or high < max(open_, close, low) - 1e-5
            or low > min(open_, close, high) + 1e-5
        ):
            continue
        result[symbol] = {
            "symbol": symbol,
            "time_key": time_key,
            "received_at_utc": received_at.isoformat(),
            "age_seconds": max(0.0, age_seconds),
            "freshness_status": "FRESH" if age_seconds <= fresh_seconds else "STALE",
            **values,
            "bar_closure": "UNPROVEN",
            "research_eligible": False,
        }
    return result


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
    payload, error, cache_hit = _load_json(source_path)
    if payload is None:
        return None, _fail(
            "UNAVAILABLE",
            error=error,
            source_path=source_path,
            source_cache_hit=False,
        )
    if payload.get("schema") != "stock_razor_canonical_market_snapshot_v1":
        return None, _fail("INVALID", error="UNSUPPORTED_SCHEMA", source_path=source_path)
    if not _safety_contract(payload):
        return None, _fail(
            "INVALID",
            error="SAFETY_CONTRACT_VIOLATION",
            source_path=source_path,
        )
    now = _now(now_utc)
    publication_age = _age_seconds(payload.get("emitted_at_utc"), now_utc=now)
    if publication_age is None or publication_age < -5:
        return None, _fail(
            "INVALID",
            error="INVALID_EMITTED_AT",
            source_path=source_path,
        )
    # The file can be rewritten by a heartbeat while the newest bar remains
    # old. Prefer provider evidence when present and retain the old publication
    # timestamp fallback for pre-migration snapshots.
    data_age = _age_seconds(
        payload.get("latest_source_timestamp_utc") or payload.get("emitted_at_utc"),
        now_utc=now,
    )
    if data_age is None or data_age < -5:
        return None, _fail(
            "INVALID",
            error="INVALID_LATEST_SOURCE_TIMESTAMP",
            source_path=source_path,
        )
    source_status = "PASS" if data_age <= max_age_seconds else "STALE"
    meta = {
        "ok": True,
        "status": source_status,
        "source_path": source_path,
        "source_age_seconds": data_age,
        "publication_age_seconds": publication_age,
        "source_cache_hit": cache_hit,
        "repo_sha": payload.get("repo_sha"),
        "runtime_instance_id": payload.get("runtime_instance_id"),
        "sequence": payload.get("sequence"),
        "emitted_at_utc": payload.get("emitted_at_utc"),
        "latest_source_timestamp_utc": payload.get("latest_source_timestamp_utc"),
        "latest_received_at_utc": payload.get("latest_received_at_utc"),
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

    started_at = perf_counter()
    if heartbeat_max_age_seconds <= 0:
        raise ValueError("heartbeat_max_age_seconds must be positive")
    now = _now(now_utc)
    source_path = _status_path(status_path)
    heartbeat, error, heartbeat_cache_hit = _load_json(source_path)
    if heartbeat is None:
        return _latency_payload(
            started_at,
            _fail(
                "UNAVAILABLE",
                error=error,
                source_path=source_path,
                heartbeat_cache_hit=False,
            ),
        )
    if heartbeat.get("type") != "us_opend_livefeed_heartbeat":
        return _latency_payload(
            started_at,
            _fail("INVALID", error="UNSUPPORTED_HEARTBEAT", source_path=source_path),
        )
    if not _safety_contract(heartbeat):
        return _latency_payload(
            started_at,
            _fail(
                "INVALID",
                error="SAFETY_CONTRACT_VIOLATION",
                source_path=source_path,
            ),
        )

    age = _age_seconds(heartbeat.get("emitted_at_utc"), now_utc=now)
    if age is None or age < -5:
        return _latency_payload(
            started_at,
            _fail("INVALID", error="INVALID_EMITTED_AT", source_path=source_path),
        )
    heartbeat_fresh = age <= heartbeat_max_age_seconds
    controller_connected = heartbeat.get("controller_lifecycle") == "CONNECTED"
    canonical_export = heartbeat.get("canonical_snapshot_export")
    canonical_export = canonical_export if isinstance(canonical_export, dict) else {}
    export_pass = canonical_export.get("status") == "PASS"
    adapter_diagnostics = heartbeat.get("adapter_diagnostics")
    adapter_diagnostics = (
        adapter_diagnostics if isinstance(adapter_diagnostics, dict) else {}
    )
    provider_callback_latency_ms = adapter_diagnostics.get(
        "provider_callback_latency_ms_last"
    )
    if (
        provider_callback_latency_ms is not None
        and (
            isinstance(provider_callback_latency_ms, bool)
            or not isinstance(provider_callback_latency_ms, (int, float))
            or not isfinite(provider_callback_latency_ms)
            or provider_callback_latency_ms < 0
        )
    ):
        return _latency_payload(
            started_at,
            _fail(
                "INVALID",
                error="INVALID_PROVIDER_CALLBACK_LATENCY",
                source_path=source_path,
            ),
        )

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
    # Sanitized postclose historical evidence only; never interpret an
    # untrusted heartbeat subtree as runtime bar-closure authorization.
    postclose = heartbeat.get("postclose_reconciliation")
    postclose_summary = None
    if isinstance(postclose, dict):
        allowed_status = {
            "NOT_DUE", "BLOCKED", "ALREADY_PRESENT",
            "PASS_HISTORICAL_ONLY", "PARTIAL_HISTORICAL_ONLY",
        }
        requests = postclose.get("provider_requests")
        seeded = postclose.get("seeded_count")
        session_date = postclose.get("session_date")
        # A previously repaired session must not be advertised as today's.
        expected_session_date = now.astimezone(
            ZoneInfo("America/New_York")
        ).date().isoformat()
        safety_ok = (
            type(session_date) is str
            and session_date == expected_session_date
            and postclose.get("status") in allowed_status
            and type(requests) is int and 0 <= requests <= 20
            and type(seeded) is int and 0 <= seeded <= requests
            and postclose.get("historical_query") is True
            and postclose.get("currentness_proven") is False
            and postclose.get("bar_closure_promotion_authorized") is False
            and postclose.get("radar_admission") == "BLOCKED"
            and postclose.get("live_trade") is False
        )
        if safety_ok:
            raw_symbols = postclose.get("symbols")
            raw_symbols = raw_symbols if isinstance(raw_symbols, dict) else {}
            qualified = (
                sum(
                    isinstance(item, dict) and item.get("status") == "PASS_HISTORICAL_ONLY"
                    for item in raw_symbols.values()
                )
                if len(raw_symbols) <= 20 else 0
            )
            postclose_summary = {
                "session_date": session_date,
                "status": postclose["status"],
                "reason": str(postclose.get("reason") or "")[:100],
                "provider_requests": requests,
                "seeded_count": seeded,
                "qualified_symbol_count": qualified,
                "historical_query": True,
                "provider_finality": "NOT_VERIFIED",
                "bar_closure_promotion_authorized": False,
                "radar_admission": "BLOCKED",
                "live_trade": False,
            }
        else:
            postclose_summary = {
                "status": "INVALID_EVIDENCE",
                "radar_admission": "BLOCKED",
                "live_trade": False,
            }
    healthy = heartbeat_fresh and controller_connected and export_pass
    status = "HEALTHY" if healthy else ("STALE" if not heartbeat_fresh else "DEGRADED")
    latest_push_observations = _qualified_latest_push_observations(
        heartbeat.get("latest_push_observations"),
        allowed_symbols=heartbeat.get("symbols"),
        now_utc=now,
    )
    latest_push_status = (
        "FRESH"
        if any(item["freshness_status"] == "FRESH" for item in latest_push_observations.values())
        else "STALE" if latest_push_observations else "UNAVAILABLE"
    )
    last_push = _aware_timestamp(heartbeat.get("last_push_utc"))
    last_push_age = (now - last_push).total_seconds() if last_push else None
    # Operational heartbeat and provider market evidence are independent.
    # A live service cannot certify realtime bars by heartbeat alone.
    source_identity_matched = (
        snapshot is not None
        and bool(snapshot_meta.get("repo_sha"))
        and snapshot_meta.get("repo_sha") == heartbeat.get("repo_sha")
        and bool(snapshot_meta.get("runtime_instance_id"))
        and snapshot_meta.get("runtime_instance_id") == heartbeat.get("runtime_instance_id")
    )
    live_source_evidence = (
        healthy
        and source_identity_matched
        and snapshot_meta.get("status") == "PASS"
        and isinstance(snapshot.get("latest_source_timestamp_utc"), str)
        and heartbeat.get("delivery_mode") == "REALTIME"
        and snapshot_meta.get("delivery_mode") == "REALTIME"
    )
    return _latency_payload(started_at, {
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
        "last_push_utc": last_push.isoformat() if last_push else None,
        "last_push_age_seconds": (
            max(0.0, last_push_age) if last_push_age is not None and last_push_age >= -5 else None
        ),
        "latest_push_status": latest_push_status,
        "latest_push_observations": latest_push_observations,
        "event_count": heartbeat.get("event_count"),
        "accepted_event_count": heartbeat.get("accepted_event_count"),
        "provider_callback_latency_ms": (
            float(provider_callback_latency_ms)
            if provider_callback_latency_ms is not None
            else None
        ),
        "provider_callback_latency_sample_count": adapter_diagnostics.get(
            "provider_callback_latency_sample_count"
        ),
        "quote_right_evidence": heartbeat.get("quote_right_evidence"),
        "postclose_reconciliation": postclose_summary,
        "canonical_export_status": canonical_export.get("status"),
        "canonical_snapshot_status": snapshot_meta.get("status"),
        "canonical_snapshot_age_seconds": snapshot_meta.get("source_age_seconds"),
        "canonical_snapshot_available": snapshot is not None,
        "heartbeat_cache_hit": heartbeat_cache_hit,
        "canonical_snapshot_cache_hit": snapshot_meta.get("source_cache_hit"),
        "cache_counts": cache_counts,
        "realtime_delivery_evidence": bool(live_source_evidence),
        "realtime_evidence_scope": (
            "SOURCE_RECENCY_AND_RUNTIME_MATCH_NOT_PER_SYMBOL"
            if live_source_evidence else "NOT_VERIFIED"
        ),
        "bar_closure_proven": heartbeat.get("bar_closure") == "PROVEN",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    })


def read_us_market_snapshots(
    symbols: Iterable[object] | None = None,
    *,
    path: str | None = None,
    now_utc: datetime | None = None,
    max_age_seconds: int = DEFAULT_SNAPSHOT_MAX_AGE_SECONDS,
) -> dict:
    """Return compact latest canonical bars for requested US symbols."""

    started_at = perf_counter()
    payload, meta = _snapshot_source(
        path,
        now_utc=now_utc,
        max_age_seconds=max_age_seconds,
    )
    if payload is None:
        return _latency_payload(started_at, meta)

    source_symbols = payload.get("symbols")
    if not isinstance(source_symbols, dict):
        return _latency_payload(
            started_at,
            _fail("INVALID", error="INVALID_SYMBOL_MAP", **{
                key: value for key, value in meta.items()
                if key not in {"ok", "status", "radar_admission", "live_trade"}
            }),
        )

    requested, invalid = _normalize_symbols(symbols)
    if invalid:
        return _latency_payload(
            started_at,
            _fail(
                "INVALID_ARGUMENT",
                error="INVALID_SYMBOL",
                invalid_symbols=list(invalid),
            ),
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

    return _latency_payload(started_at, {
        **meta,
        "symbols": result,
        "missing_symbols": missing,
        "data_available": any(
            any(value is not None for value in item["latest"].values())
            for item in result.values()
        ),
    })


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

    started_at = perf_counter()
    normalized = _normalize_symbol(symbol)
    if normalized is None:
        return _latency_payload(
            started_at,
            _fail("INVALID_ARGUMENT", error="INVALID_SYMBOL"),
        )
    frame = str(timeframe or "").strip().lower()
    if frame not in SUPPORTED_TIMEFRAMES:
        return _latency_payload(
            started_at,
            _fail(
                "INVALID_ARGUMENT",
                error="UNSUPPORTED_TIMEFRAME",
                supported_timeframes=list(SUPPORTED_TIMEFRAMES),
            ),
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 480:
        return _latency_payload(
            started_at,
            _fail("INVALID_ARGUMENT", error="INVALID_LIMIT", limit_max=480),
        )

    payload, meta = _snapshot_source(
        path,
        now_utc=now_utc,
        max_age_seconds=max_age_seconds,
    )
    if payload is None:
        return _latency_payload(started_at, meta)
    source_symbols = payload.get("symbols")
    source_symbols = source_symbols if isinstance(source_symbols, dict) else {}
    item = source_symbols.get(normalized)
    if not isinstance(item, dict):
        return _latency_payload(started_at, {
            **meta,
            "ok": False,
            "status": "NO_DATA",
            "symbol": normalized,
            "timeframe": frame,
            "bars": [],
            "bar_count": 0,
            "total_bar_count": 0,
        })
    frames = item.get("timeframes")
    frames = frames if isinstance(frames, dict) else {}
    bars = frames.get(frame)
    bars = [bar for bar in bars if isinstance(bar, dict)] if isinstance(bars, list) else []
    selected = bars[-limit:]
    return _latency_payload(started_at, {
        **meta,
        "ok": bool(selected),
        "status": meta["status"] if selected else "NO_DATA",
        "symbol": normalized,
        "timeframe": frame,
        "bar_count": len(selected),
        "total_bar_count": len(bars),
        "bars": selected,
    })


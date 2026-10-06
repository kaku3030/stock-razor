from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from data_provider.market_data_adapter import Bar, MarketDataHealth
from src.services.realtime_market_data import MarketDataSnapshot


SCHEMA = "stock_razor_canonical_market_snapshot_v1"


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("canonical snapshot datetimes must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _health_payload(health: MarketDataHealth | None) -> dict | None:
    if health is None:
        return None
    return {
        "score": health.score,
        "grade": health.grade.value,
        "signal_permission": health.signal_permission.value,
        "quality_flags": list(health.quality_flags),
    }


def _bar_payload(bar: Bar) -> dict:
    return {
        "symbol": bar.symbol,
        "market": bar.market,
        "asset_type": bar.asset_type,
        "timeframe": bar.timeframe,
        "bar_start_utc": _iso(bar.bar_start),
        "bar_end_utc": _iso(bar.bar_end),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "amount": bar.amount,
        "vwap": bar.vwap,
        "provider": bar.provider,
        "feed": bar.feed,
        "source_timestamp_utc": _iso(bar.source_timestamp),
        "received_at_utc": _iso(bar.received_at),
        "session": bar.session,
        "is_closed": bar.is_closed,
        "is_complete": bar.is_complete,
        "fallback_from": bar.fallback_from,
        "fallback_reason": bar.fallback_reason,
        "latency_ms": bar.latency_ms,
        "freshness_ms": bar.freshness_ms,
        "quality_flags": list(bar.quality_flags),
        "health": _health_payload(bar.health),
    }


def _snapshot_payload(snapshot: MarketDataSnapshot) -> dict:
    return {
        "symbol": snapshot.symbol,
        "as_of_utc": _iso(snapshot.as_of),
        "provider": snapshot.provider,
        "feed": snapshot.feed,
        "fallback_from": snapshot.fallback_from,
        "fallback_reason": snapshot.fallback_reason,
        "owner_identity": snapshot.owner_identity,
        "runtime_generation": snapshot.runtime_generation,
        "health": _health_payload(snapshot.health),
        "timeframes": {
            "1m": [_bar_payload(bar) for bar in snapshot.minute_bars],
            "5m": [_bar_payload(bar) for bar in snapshot.bars_5m],
            "15m": [_bar_payload(bar) for bar in snapshot.bars_15m],
            "1h": [_bar_payload(bar) for bar in snapshot.bars_1h],
        },
    }


def build_canonical_snapshot_export(
    snapshots: Mapping[str, MarketDataSnapshot],
    *,
    runtime_instance_id: str,
    repo_sha: str,
    sequence: int,
    emitted_at_utc: datetime,
    market_state_us: str,
    cache_session_us: str,
    bar_closure: str = "UNPROVEN",
) -> dict:
    runtime = str(runtime_instance_id).strip()
    sha = str(repo_sha).strip().lower()
    if not runtime:
        raise ValueError("runtime_instance_id is required")
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ValueError("repo_sha must be an exact 40-character git SHA")
    if sequence < 0:
        raise ValueError("sequence must be non-negative")
    normalized_bar_closure = str(bar_closure or "").strip().upper()
    if normalized_bar_closure not in {"UNPROVEN", "PROVEN"}:
        raise ValueError("bar_closure must be UNPROVEN or PROVEN")

    normalized = {}
    for key, snapshot in snapshots.items():
        symbol = str(key).strip().upper()
        if not symbol or snapshot.symbol.upper() != symbol:
            raise ValueError("snapshot mapping key must match snapshot.symbol")
        normalized[symbol] = _snapshot_payload(snapshot)

    return {
        "schema": SCHEMA,
        "runtime_instance_id": runtime,
        "repo_sha": sha,
        "sequence": sequence,
        "emitted_at_utc": _iso(emitted_at_utc),
        "market_state_us": str(market_state_us or "UNKNOWN"),
        "cache_session_us": str(cache_session_us or "unknown"),
        "delivery_mode": "UNKNOWN",
        "bar_closure": normalized_bar_closure,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "symbols": normalized,
    }


def write_canonical_snapshot_export(path: str | os.PathLike[str], payload: Mapping) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)

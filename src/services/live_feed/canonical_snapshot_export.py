from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Mapping

from data_provider.market_data_adapter import Bar, MarketDataHealth
from src.services.realtime_market_data import MarketDataSnapshot
from src.services.live_feed.runtime_publication import write_runtime_json


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


def _latest_bar_timestamp(snapshots: Mapping[str, MarketDataSnapshot], field: str) -> str | None:
    values = []
    for snapshot in snapshots.values():
        for bars in (
            snapshot.minute_bars,
            snapshot.bars_5m,
            snapshot.bars_15m,
            snapshot.bars_1h,
        ):
            for bar in bars:
                value = getattr(bar, field, None)
                if value is not None:
                    values.append(value)
    if not values:
        return None
    return _iso(max(values))


def build_canonical_snapshot_export(
    snapshots: Mapping[str, MarketDataSnapshot],
    *,
    runtime_instance_id: str,
    repo_sha: str,
    sequence: int,
    emitted_at_utc: datetime,
    market_state_us: str,
    cache_session_us: str,
    delivery_mode: str = "UNKNOWN",
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
    normalized_delivery_mode = str(delivery_mode or "").strip().upper()
    if normalized_delivery_mode not in {"UNKNOWN", "REALTIME"}:
        raise ValueError("delivery_mode must be UNKNOWN or REALTIME")
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
        # Publication time describes when this immutable export was written.
        # These fields describe the newest actual provider evidence inside it;
        # readers must use them for data freshness so a heartbeat refresh can
        # never launder an old bar into a fresh market snapshot.
        "latest_source_timestamp_utc": _latest_bar_timestamp(snapshots, "source_timestamp"),
        "latest_received_at_utc": _latest_bar_timestamp(snapshots, "received_at"),
        "market_state_us": str(market_state_us or "UNKNOWN"),
        "cache_session_us": str(cache_session_us or "unknown"),
        "delivery_mode": normalized_delivery_mode,
        "bar_closure": normalized_bar_closure,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "symbols": normalized,
    }


def write_canonical_snapshot_export(path: str | os.PathLike[str], payload: Mapping) -> None:
    write_runtime_json(path, payload)

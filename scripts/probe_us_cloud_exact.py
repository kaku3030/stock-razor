#!/usr/bin/env python3
"""Bounded, read-only US cloud evidence probe.

This probe reads the existing US live-feed and Radar exports only.  It never
creates a provider context, subscribes, writes canonical data, or changes an
admission gate.  Missing evidence stays UNKNOWN/NOT_VERIFIED.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from typing import Any


DEFAULT_SYMBOLS = (
    "US.AMD", "US.NVDA", "US.TSLA", "US.AAPL", "US.QQQ",
    "US.GLDM", "US.LITE", "US.AAOI", "US.CIEN",
)
LIVEFEED_SERVICE = "stock-razor-us-livefeed.service"
RADAR_SERVICE = "stock-razor-us-radar.service"
LIVEFEED_PATH = "/run/stock-razor-us-livefeed/latest-heartbeat.json"
SNAPSHOT_PATH = "/run/stock-razor-us-livefeed/canonical-market-snapshot.json"
RADAR_PATH = "/run/stock-razor-us-radar/latest-research-state.json"
MAX_JSON_BYTES = 5_000_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _read_json(path: str) -> dict[str, Any] | None:
    try:
        source = Path(path)
        if not source.is_file() or source.stat().st_size > MAX_JSON_BYTES:
            return None
        with source.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None


def _active(service: str) -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", service],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "active"


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50_ms": None, "p95_ms": None, "max_ms": None}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 3)

    return {
        "p50_ms": percentile(0.50),
        "p95_ms": percentile(0.95),
        "max_ms": round(max(ordered), 3),
    }


def _sample(heartbeat: dict[str, Any], symbols: tuple[str, ...]) -> dict[str, Any]:
    currentness = heartbeat.get("k1m_currentness")
    currentness = currentness if isinstance(currentness, dict) else {}
    time_keys = heartbeat.get("latest_k1m_time_keys")
    time_keys = time_keys if isinstance(time_keys, dict) else {}
    return {
        "sequence": heartbeat.get("sequence"),
        "event_count": heartbeat.get("event_count"),
        "last_push_utc": heartbeat.get("last_push_utc"),
        "time_keys": {symbol: time_keys.get(symbol) for symbol in symbols},
        "freshness": {
            symbol: {
                "status": (currentness.get(symbol) or {}).get("status"),
                "age_seconds": (currentness.get(symbol) or {}).get("age_seconds"),
            }
            for symbol in symbols
        },
        "adapter_diagnostics": heartbeat.get("adapter_diagnostics"),
        "observed_at_utc": _now().isoformat(),
    }


def _label_age(seconds: object) -> dict[str, Any]:
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return {"seconds": None, "classification": "UNKNOWN"}
    if seconds < 0:
        return {"seconds": seconds, "classification": "NEGATIVE_END_LABEL_AGE_NOT_LATENCY"}
    return {"seconds": seconds, "classification": "END_LABEL_AGE_NOT_PROVIDER_LATENCY"}


def probe(
    *,
    expected_sha: str,
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    duration_seconds: int = 30,
    interval_seconds: float = 2.0,
    sleep=time.sleep,
) -> dict[str, Any]:
    if len(expected_sha) != 40 or any(char not in "0123456789abcdef" for char in expected_sha.lower()):
        raise ValueError("expected_sha must be a 40-character SHA")
    if not symbols or any(not symbol.startswith("US.") for symbol in symbols):
        raise ValueError("probe symbols must be US.*")
    if not 5 <= duration_seconds <= 120:
        raise ValueError("duration_seconds must be between 5 and 120")
    if not 0.5 <= interval_seconds <= 10:
        raise ValueError("interval_seconds must be between 0.5 and 10")

    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + duration_seconds
    while True:
        heartbeat = _read_json(LIVEFEED_PATH)
        if heartbeat is not None:
            samples.append(_sample(heartbeat, symbols))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sleep(min(interval_seconds, remaining))

    heartbeat = _read_json(LIVEFEED_PATH) or {}
    snapshot = _read_json(SNAPSHOT_PATH) or {}
    radar = _read_json(RADAR_PATH) or {}
    heartbeat_sha = heartbeat.get("repo_sha")
    radar_sha = radar.get("expected_source_repo_sha")
    exact_sha = heartbeat_sha == expected_sha and radar_sha == expected_sha
    event_counts = [item.get("event_count") for item in samples if isinstance(item.get("event_count"), int)]
    increasing_events = any(later > earlier for earlier, later in zip(event_counts, event_counts[1:]))
    time_progress = {
        symbol: any(
            earlier.get("time_keys", {}).get(symbol)
            and later.get("time_keys", {}).get(symbol)
            and later["time_keys"][symbol] > earlier["time_keys"][symbol]
            for earlier, later in zip(samples, samples[1:])
        )
        for symbol in symbols
    }
    freshness = {
        symbol: (heartbeat.get("k1m_currentness", {}).get(symbol) or {})
        for symbol in symbols
    }
    fresh_symbols = {
        symbol: item.get("status") == "PASS"
        and isinstance(item.get("age_seconds"), (int, float))
        and not isinstance(item.get("age_seconds"), bool)
        and item.get("age_seconds") >= 0
        for symbol, item in freshness.items()
    }
    cache_session = heartbeat.get("cache_session_us")
    cache_segregation = (
        cache_session in {"US_PRE_MARKET", "US_RTH", "US_POST_MARKET", "UNKNOWN"}
        and all(symbol.startswith("US.") for symbol in symbols)
        and not any(str(symbol).startswith(("CN.", "SH.", "SZ.")) for symbol in symbols)
    )
    bar_closure = heartbeat.get("bar_closure") == "PROVEN"
    intraday_closure = heartbeat.get("intraday_closure_15m_60m")
    intraday_closure = intraday_closure if isinstance(intraday_closure, dict) else {}
    cache = heartbeat.get("canonical_cache")
    cache = cache if isinstance(cache, dict) else {}
    closure_counts = {
        symbol: {
            "15m_bars": (cache.get(symbol) or {}).get("bar_count_15m"),
            "60m_bars": (cache.get(symbol) or {}).get("bar_count_1h"),
            "closure_evidence": "PROVEN" if bar_closure else "UNPROVEN",
        }
        for symbol in symbols
    }
    radar_latency = radar.get("canonical_sequence_stage_latency")
    radar_latency = radar_latency if isinstance(radar_latency, dict) else {}
    adapter_diagnostics = heartbeat.get("adapter_diagnostics")
    adapter_diagnostics = adapter_diagnostics if isinstance(adapter_diagnostics, dict) else {}
    configured_symbols = heartbeat.get("symbols")
    configured_symbols = {
        item for item in configured_symbols if isinstance(item, str)
    } if isinstance(configured_symbols, list) else set()
    subscribed_symbols = heartbeat.get("subscribed")
    subscribed_symbols = {
        item for item in subscribed_symbols if isinstance(item, str)
    } if isinstance(subscribed_symbols, list) else set()
    quote_right = heartbeat.get("quote_right_evidence")
    quote_right = quote_right if isinstance(quote_right, dict) else {}
    symbol_coverage = {
        symbol: {
            "configured": symbol in configured_symbols,
            "subscribed": symbol in subscribed_symbols,
            "permission_query_status": quote_right.get("query_status", "UNKNOWN"),
            "status": "PASS" if symbol in configured_symbols and symbol in subscribed_symbols and quote_right.get("query_status") == "PASS" else "NOT_VERIFIED",
        }
        for symbol in symbols
    }
    label_age = {
        symbol: _label_age((freshness.get(symbol) or {}).get("age_seconds"))
        for symbol in symbols
    }

    return {
        "schema": "stock_razor_us_exact_cloud_probe_v1",
        "expected_repo_sha": expected_sha,
        "observed_livefeed_repo_sha": heartbeat_sha,
        "observed_radar_source_sha": radar_sha,
        "runtime_exact_sha": "PASS" if exact_sha else "NOT_VERIFIED",
        "symbols": list(symbols),
        "symbol_coverage": {
            "permission_scope": "ACCOUNT_LEVEL_QOTRIGHT_NOT_PER_SYMBOL_ENTITLEMENT",
            "per_symbol": symbol_coverage,
        },
        "holdings_integrity": {
            "status": "NOT_VERIFIED",
            "reason": "READ_ONLY_MARKET_PROBE_DOES_NOT_READ_OR_MUTATE_POSITIONS",
        },
        "duration_seconds": duration_seconds,
        "sample_count": len(samples),
        "continuous_live_quote_sequence": {
            "status": "PASS" if exact_sha and increasing_events and all(time_progress.values()) else "NOT_VERIFIED",
            "increasing_event_count": increasing_events,
            "time_key_progress": time_progress,
            "event_count_last": event_counts[-1] if event_counts else None,
        },
        "timestamp_freshness": {
            "status": "PASS" if exact_sha and all(fresh_symbols.values()) else "NOT_VERIFIED",
            "per_symbol": freshness,
        },
        "bar_closure_15m_60m": {
            "status": "PASS" if exact_sha and bar_closure and heartbeat.get("intraday_closure_15m_60m_summary") == "PASS" else "NOT_VERIFIED",
            "per_symbol": intraday_closure or closure_counts,
            "source_bar_closure": heartbeat.get("bar_closure", "UNPROVEN"),
            "source_intraday_closure_summary": heartbeat.get("intraday_closure_15m_60m_summary", "UNKNOWN"),
        },
        "latency_ms": {
            "provider_to_callback": {
                "status": "NOT_VERIFIED",
                "scope": "NO_INDEPENDENT_PROVIDER_ARRIVAL_TIMESTAMP",
                "reason": "provider_arrival_time_not_emitted_by_sdk_contract",
                "p50_ms": None,
                "p95_ms": None,
                "max_ms": None,
            },
            "end_label_age": {
                "status": "OBSERVED" if any(item["classification"] != "UNKNOWN" for item in label_age.values()) else "NOT_VERIFIED",
                "scope": "PROVIDER_END_LABEL_TO_LOCAL_OBSERVATION_ONLY_NOT_NETWORK_LATENCY",
                "per_symbol": label_age,
            },
            "callback_processing_only": {
                "status": "OBSERVED" if adapter_diagnostics.get("provider_callback_latency_sample_count") else "NOT_VERIFIED",
                "scope": "SDK_CALLBACK_HANDLER_PROCESSING_ONLY_NOT_PROVIDER_WIRE_LATENCY",
                "p50_ms": None,
                "p95_ms": None,
                "max_ms": adapter_diagnostics.get("provider_callback_latency_ms_max"),
                "sample_count": adapter_diagnostics.get("provider_callback_latency_sample_count"),
            },
            "callback_to_radar": radar_latency.get("canonical_export_to_radar_completion") or _stats([]),
            "provider_to_radar": "NOT_VERIFIED",
        },
        "clock_skew": {
            "status": "NOT_VERIFIED",
            "reason": "No independent provider clock or NTP witness in the existing US runtime export",
            "heartbeat_age_seconds": (
                (_now() - _parse_time(heartbeat.get("emitted_at_utc"))).total_seconds()
                if _parse_time(heartbeat.get("emitted_at_utc")) else None
            ),
        },
        "cache_segregation": {
            "status": "PASS" if cache_segregation else "NOT_VERIFIED",
            "cache_session_us": cache_session,
            "reads": [LIVEFEED_PATH, SNAPSHOT_PATH, RADAR_PATH],
            "cn_requests": 0,
        },
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "shadow_only": True,
        "live_trade": "NO",
        "samples": samples,
        "latest_heartbeat": heartbeat,
        "latest_radar": radar,
        "snapshot_repo_sha": snapshot.get("repo_sha"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--duration-seconds", type=int, default=30)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    args = parser.parse_args()
    symbols = tuple(item.strip().upper() for item in args.symbols.split(",") if item.strip())
    print(json.dumps(probe(expected_sha=args.expected_sha, symbols=symbols, duration_seconds=args.duration_seconds), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

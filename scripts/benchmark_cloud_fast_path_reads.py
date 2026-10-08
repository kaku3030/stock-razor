#!/usr/bin/env python3
"""Benchmark existing cloud read surfaces without inventing missing layers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from math import isfinite
from data_provider.cn_cloud_runtime_reader import read_cn_market_data
from data_provider.cn_radar_runtime_reader import read_cn_radar_analysis
from data_provider.us_canonical_runtime_reader import (
    read_us_livefeed_health,
    read_us_market_snapshots,
)
from data_provider.us_radar_runtime_reader import read_us_radar_analysis
from src.services.cloud_fast_path_metrics import FastPathSample, summarize_fast_path


def _number(payload: dict, key: str) -> float | None:
    value = payload.get(key)
    if not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value) and value >= 0:
        return float(value)
    return None


def _source_age_ms(*payloads: dict) -> float | None:
    values = []
    for payload in payloads:
        age = payload.get("source_age_seconds")
        if not isinstance(age, bool) and isinstance(age, (int, float)) and isfinite(age) and age >= 0:
            values.append(float(age) * 1000)
    return max(values) if values else None


def _status_success(*payloads: dict) -> bool:
    accepted = {"PASS", "HEALTHY"}
    return all(payload.get("status") in accepted for payload in payloads)


def benchmark_us(symbols: list[str], iterations: int) -> list[FastPathSample]:
    samples = []
    for index in range(iterations):
        health = read_us_livefeed_health()
        canonical = read_us_market_snapshots(symbols)
        radar = read_us_radar_analysis(symbols)
        samples.append(FastPathSample(
            sample_id=f"us-{index + 1}",
            market="us",
            observed_at=datetime.now(timezone.utc),
            provider="futu-opend",
            provider_latency_ms=None,
            provider_callback_processing_latency_ms=_number(
                health, "provider_callback_latency_ms"
            ),
            canonical_latency_ms=_number(canonical, "read_latency_ms"),
            radar_analysis_latency_ms=_number(radar, "radar_analysis_latency_ms"),
            radar_read_latency_ms=_number(radar, "read_latency_ms"),
            data_to_radar_latency_ms=_number(radar, "data_to_radar_latency_ms"),
            mcp_latency_ms=None,
            chatgpt_access_latency_ms=None,
            e2e_latency_ms=None,
            freshness_ms=_source_age_ms(canonical, radar),
            success=_status_success(health, canonical, radar),
            retry_count=None,
            fallback_count=None,
            freshness_state="UNKNOWN",
            data_completeness="UNKNOWN",
            data_correctness_state="UNKNOWN",
            analysis_quality_state="UNKNOWN",
            repo_sha=radar.get("worker_repo_sha") or canonical.get("repo_sha"),
            runtime_instance_id=(
                radar.get("runtime_instance_id")
                or canonical.get("runtime_instance_id")
            ),
        ))
    return samples


def benchmark_cn(symbols: list[str], timeframe: str, iterations: int) -> list[FastPathSample]:
    samples = []
    for index in range(iterations):
        canonical_rows = [
            read_cn_market_data(symbol, timeframe=timeframe, limit=120)
            for symbol in symbols
        ]
        radar = read_cn_radar_analysis(symbols)
        canonical_latencies = [
            _number(payload, "read_latency_ms") for payload in canonical_rows
        ]
        canonical_latency = (
            sum(canonical_latencies)
            if canonical_latencies and all(value is not None for value in canonical_latencies)
            else None
        )
        provider_latencies = [
            value
            for payload in canonical_rows
            if (value := _number(payload, "provider_request_latency_ms")) is not None
        ]
        providers = {
            str(payload.get("provider_used")).strip()
            for payload in canonical_rows
            if payload.get("provider_used")
        }
        fallback_rows = [
            payload for payload in canonical_rows if payload.get("fallback_from")
        ]
        fallback_providers = {
            str(payload.get("provider_used")).strip()
            for payload in fallback_rows
            if payload.get("provider_used")
        }
        all_payloads = [*canonical_rows, radar]
        samples.append(FastPathSample(
            sample_id=f"cn-{index + 1}",
            market="cn",
            observed_at=datetime.now(timezone.utc),
            provider=(
                next(iter(providers))
                if len(providers) == 1
                else ("mixed" if providers else None)
            ),
            provider_latency_ms=None,
            provider_request_path_latency_ms=(
                max(provider_latencies)
                if len(provider_latencies) == len(canonical_rows)
                else None
            ),
            canonical_latency_ms=(
                round(canonical_latency, 3) if canonical_latency is not None else None
            ),
            radar_analysis_latency_ms=_number(radar, "radar_analysis_latency_ms"),
            radar_read_latency_ms=_number(radar, "read_latency_ms"),
            data_to_radar_latency_ms=_number(radar, "data_to_radar_latency_ms"),
            mcp_latency_ms=None,
            chatgpt_access_latency_ms=None,
            e2e_latency_ms=None,
            freshness_ms=_source_age_ms(*all_payloads),
            success=_status_success(*all_payloads),
            retry_count=None,
            # Positive fallback evidence is countable; a missing fallback field
            # alone does not prove that fallback_count == 0.
            fallback_count=len(fallback_rows) if fallback_rows else None,
            fallback_provider=(
                next(iter(fallback_providers))
                if len(fallback_providers) == 1
                else ("mixed" if fallback_providers else None)
            ),
            freshness_state="UNKNOWN",
            data_completeness="UNKNOWN",
            data_correctness_state="UNKNOWN",
            analysis_quality_state="UNKNOWN",
            repo_sha=radar.get("worker_repo_sha") or radar.get("source_repo_sha"),
            runtime_instance_id=(
                radar.get("runtime_instance_id")
                or radar.get("source_runtime_instance_id")
            ),
        ))
    return samples


def _allow_status(value: object, allowed: frozenset[str]) -> str:
    return value if isinstance(value, str) and value in allowed else "UNKNOWN"


def cn_symbol_read_diagnostics(symbols: list[str], timeframe: str) -> dict:
    """One bounded read per symbol; never output raw bars/errors/credentials.

    This is a read-surface status check, not source qualification, provider
    network measurement, continuity proof or Radar admission.
    """
    statuses = frozenset({"PASS", "STALE", "NO_DATA", "INVALID", "UNKNOWN", "BLOCKED"})
    providers = frozenset({"eastmoney", "tencent"})
    semantics = frozenset({"BAR_END", "BAR_START", "DAILY_DATE", "UNKNOWN"})
    currentness = frozenset({"PROVEN", "UNPROVEN", "STALE", "UNKNOWN"})
    result = {}
    for symbol in dict.fromkeys(symbols):
        row = read_cn_market_data(symbol, timeframe=timeframe, limit=1)
        source_count = row.get("total_row_count")
        result[symbol] = {
            "read_status": _allow_status(row.get("status"), statuses),
            "provider_used": _allow_status(row.get("provider_used"), providers),
            "fallback_from": _allow_status(row.get("fallback_from"), providers),
            "timestamp_semantic": _allow_status(row.get("timestamp_semantic"), semantics),
            "symbol_timestamp_semantics_proven": (
                row.get("symbol_intraday_timestamp_semantics_proven") is True
            ),
            "currentness": _allow_status(row.get("currentness"), currentness),
            "symbol_currentness_proven": (
                row.get("symbol_intraday_currentness_proven") is True
            ),
            "source_age_seconds": (
                _number(row, "source_age_seconds")
            ),
            "observed_row_count": (
                source_count
                if isinstance(source_count, int)
                and not isinstance(source_count, bool)
                and source_count >= 0
                else None
            ),
            "radar_admission": "BLOCKED",
            "live_trade": False,
            "can_confirm_signal": False,
        }
    return {
        "scope": "CN_READ_ONLY_SOURCE_DIAGNOSTIC_NOT_ADMISSION",
        "timeframe": timeframe,
        "requested_symbols": len(result),
        "symbols": result,
        "data_qualification": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def us_cloud_read_diagnostics(symbols: list[str]) -> dict:
    """Read-only health/coverage view; no price bars or raw errors are logged."""
    statuses = frozenset({
        "PASS", "HEALTHY", "STALE", "DEGRADED", "BLOCKED",
        "INVALID", "NO_DATA", "UNKNOWN",
    })
    market_states = frozenset({
        "OPEN", "CLOSED", "PRE_MARKET", "AFTER_HOURS",
        "EXTENDED_HOURS", "UNKNOWN",
    })
    delivery_modes = frozenset({"REALTIME", "DELAYED", "UNPROVEN", "UNKNOWN"})
    closure_modes = frozenset({"PROVEN", "UNPROVEN", "UNKNOWN"})

    health = read_us_livefeed_health()
    canonical = read_us_market_snapshots(symbols)
    radar = read_us_radar_analysis(symbols)
    source_symbols = canonical.get("symbols")
    source_symbols = source_symbols if isinstance(source_symbols, dict) else {}
    coverage = {}
    for symbol in dict.fromkeys(symbols):
        info = source_symbols.get(symbol)
        info = info if isinstance(info, dict) else {}
        source_counts = info.get("counts")
        source_counts = source_counts if isinstance(source_counts, dict) else {}
        counts = {
            frame: (
                source_counts[frame]
                if isinstance(source_counts.get(frame), int)
                and not isinstance(source_counts.get(frame), bool)
                and source_counts[frame] >= 0
                else None
            )
            for frame in ("1m", "5m", "15m", "1h")
        }
        coverage[symbol] = {
            "symbol_present": symbol in source_symbols,
            "bar_counts": counts,
            "any_bars_observed": any(
                value is not None and value > 0 for value in counts.values()
            ),
            "radar_admission": "BLOCKED",
            "live_trade": False,
            "can_confirm_signal": False,
        }
    return {
        "scope": "US_READ_ONLY_SOURCE_DIAGNOSTIC_NOT_ADMISSION",
        "livefeed_status": _allow_status(health.get("status"), statuses),
        "market_state_us": _allow_status(
            health.get("market_state_us"), market_states
        ),
        "delivery_mode": _allow_status(health.get("delivery_mode"), delivery_modes),
        "bar_closure": _allow_status(health.get("bar_closure"), closure_modes),
        "realtime_delivery_evidence": health.get("realtime_delivery_evidence") is True,
        "bar_closure_proven": health.get("bar_closure_proven") is True,
        "canonical_export_status": _allow_status(
            health.get("canonical_export_status"), statuses
        ),
        "canonical_snapshot_status": _allow_status(
            canonical.get("status"), statuses
        ),
        "canonical_snapshot_age_seconds": _number(canonical, "source_age_seconds"),
        "canonical_data_available": canonical.get("data_available") is True,
        "radar_status": _allow_status(radar.get("status"), statuses),
        "radar_poll_status": _allow_status(radar.get("poll_status"), statuses),
        "radar_source_age_seconds": _number(radar, "source_age_seconds"),
        "symbols": coverage,
        "data_qualification": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "can_confirm_signal": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", choices=("us", "cn"), required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--timeframe", default="15m")
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")

    if args.market == "us":
        samples = benchmark_us(args.symbols, args.iterations)
    else:
        samples = benchmark_cn(args.symbols, args.timeframe, args.iterations)

    source_diagnostics = (
        cn_symbol_read_diagnostics(args.symbols, args.timeframe)
        if args.market == "cn"
        else None
    )
    us_diagnostics = (
        us_cloud_read_diagnostics(args.symbols)
        if args.market == "us"
        else None
    )
    print(json.dumps({
        "schema": "stock_razor_cloud_fast_path_benchmark_v1",
        "cn_symbol_read_diagnostics": source_diagnostics,
        "us_cloud_read_diagnostics": us_diagnostics,
        "measurement_boundary": "RUNTIME_TELEMETRY_PLUS_READ_SURFACES",
        "missing_layers_are_not_inferred": True,
        "summary": summarize_fast_path(samples),
        "samples": [sample.to_dict() for sample in samples],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

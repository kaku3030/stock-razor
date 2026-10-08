#!/usr/bin/env python3
"""Benchmark existing cloud read surfaces without inventing missing layers."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from data_provider.cn_cloud_runtime_reader import read_cn_market_data
from data_provider.cn_radar_runtime_reader import read_cn_radar_analysis
from data_provider.us_canonical_runtime_reader import read_us_market_snapshots
from data_provider.us_radar_runtime_reader import read_us_radar_analysis
from src.services.cloud_fast_path_metrics import FastPathSample, summarize_fast_path


def _number(payload: dict, key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, (int, float)) and value >= 0:
        return float(value)
    return None


def _source_age_ms(*payloads: dict) -> float | None:
    values = []
    for payload in payloads:
        age = payload.get("source_age_seconds")
        if isinstance(age, (int, float)) and age >= 0:
            values.append(float(age) * 1000)
    return max(values) if values else None


def _status_success(*payloads: dict) -> bool:
    accepted = {"PASS", "HEALTHY"}
    return all(payload.get("status") in accepted for payload in payloads)


def benchmark_us(symbols: list[str], iterations: int) -> list[FastPathSample]:
    samples = []
    for index in range(iterations):
        canonical = read_us_market_snapshots(symbols)
        radar = read_us_radar_analysis(symbols)
        samples.append(FastPathSample(
            sample_id=f"us-{index + 1}",
            market="us",
            observed_at=datetime.now(timezone.utc),
            provider="futu-opend",
            canonical_latency_ms=_number(canonical, "read_latency_ms"),
            radar_read_latency_ms=_number(radar, "read_latency_ms"),
            e2e_latency_ms=None,
            freshness_ms=_source_age_ms(canonical, radar),
            success=_status_success(canonical, radar),
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
        canonical_latency = sum(
            _number(payload, "read_latency_ms") or 0.0
            for payload in canonical_rows
        )
        all_payloads = [*canonical_rows, radar]
        samples.append(FastPathSample(
            sample_id=f"cn-{index + 1}",
            market="cn",
            observed_at=datetime.now(timezone.utc),
            provider=None,
            canonical_latency_ms=round(canonical_latency, 3),
            radar_read_latency_ms=_number(radar, "read_latency_ms"),
            e2e_latency_ms=None,
            freshness_ms=_source_age_ms(*all_payloads),
            success=_status_success(*all_payloads),
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

    print(json.dumps({
        "schema": "stock_razor_cloud_fast_path_benchmark_v1",
        "measurement_boundary": "READ_SURFACES_ONLY",
        "missing_layers_are_not_inferred": True,
        "summary": summarize_fast_path(samples),
        "samples": [sample.to_dict() for sample in samples],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

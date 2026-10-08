#!/usr/bin/env python3
"""AWS US/CN source selection SHADOW witness; exclusively existing cache reads.

No provider sockets, new subscriptions, canonical writes, service restarts,
trading or qualification promotions. Missing independent evidence stays UNKNOWN.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from math import isfinite
from typing import Any, Callable

from src.services.data_fabric_source_arbiter_policy import (
    Candidate,
    propose_authoritative_source,
)

US_SYMBOLS = ("US.AMD", "US.NVDA")
CN_SYMBOLS = ("159611", "518880")
US_TIMEFRAME = "15m"
CN_TIMEFRAME = "15m"
STATUS_ALLOWLIST = frozenset({"PASS", "STALE", "NO_DATA", "INVALID", "UNAVAILABLE",
                              "DEGRADED", "HEALTHY", "UNKNOWN", "BLOCKED"})
MAX_EVIDENCE_AGE_MS = 120_000.0


def _safe_status(value: Any) -> str:
    return value if isinstance(value, str) and value in STATUS_ALLOWLIST else "UNKNOWN"


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if isfinite(value) and value >= 0 else None


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _observed_at(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is not None and stamp.utcoffset() is not None:
                return stamp.astimezone(timezone.utc)
        except ValueError:
            pass
    # Explicit stale sentinel, never fake "now" for missing timestamps.
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _candidate(
    *, source: str, market: str, symbol: str, timeframe: str,
    info: dict, process_healthy: str, latency_ms: float | None,
) -> Candidate:
    age = _finite_number(info.get("source_age_seconds"))
    return Candidate(
        source=source, market=market, symbol=symbol, timeframe=timeframe,
        observed_at_utc=_observed_at(info.get("emitted_at_utc")),
        latency_ms=latency_ms,
        source_age_ms=round(age * 1000, 3) if age is not None else None,
        sequence=_count(info.get("sequence")),
        process_healthy=process_healthy,
        # Service heartbeat, bar count and timestamp label do not independently
        # prove live venue connectivity, entitlement or data correctness.
        reachable="UNKNOWN",
        entitlement_qualified="UNKNOWN",
        freshness_qualified="UNKNOWN",
        continuity_qualified="UNKNOWN",
        completeness_qualified="UNKNOWN",
        correctness_qualified="UNKNOWN",
        source_progress_qualified="UNKNOWN",
        crosscheck_status="UNKNOWN",
    )


def _shadow_entry(
    *, market: str, symbol: str, timeframe: str, source: str | None,
    reader_status: str, observed_bar_count: int | None,
    info: dict, now: datetime, process_healthy: str = "UNKNOWN",
    latency_ms: float | None = None,
) -> dict:
    candidates = []
    if source is not None:
        candidates.append(_candidate(
            source=source, market=market, symbol=symbol, timeframe=timeframe,
            info=info, process_healthy=process_healthy, latency_ms=latency_ms,
        ))
    decision = propose_authoritative_source(
        market, symbol, timeframe, candidates, now_utc=now,
        max_age_ms=120_000 if market == "US" else 180_000,
        max_observation_age_ms=MAX_EVIDENCE_AGE_MS,
    )
    return {
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "reported_source": source or "UNKNOWN",
        "read_status": reader_status,
        "observed_bar_count": observed_bar_count,
        "measurement_scope": "AWS_EXISTING_CACHE_ONLY",
        "decision": decision,
    }


def audit_cloud_shadow(
    *,
    us_health: dict,
    us_snapshot: dict,
    cn_reads: dict[str, dict],
    now: datetime,
) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must have timezone")
    if not all(isinstance(item, dict) for item in [us_health, us_snapshot]):
        raise ValueError("invalid reader response")
    if not isinstance(cn_reads, dict):
        raise ValueError("invalid CN reader response")

    entries = []
    us_status = _safe_status(us_snapshot.get("status"))
    health_status = _safe_status(us_health.get("status"))
    us_map = us_snapshot.get("symbols")
    us_map = us_map if isinstance(us_map, dict) else {}
    for symbol in US_SYMBOLS:
        item = us_map.get(symbol)
        item = item if isinstance(item, dict) else {}
        counts = item.get("counts")
        counts = counts if isinstance(counts, dict) else {}
        bars = _count(counts.get(US_TIMEFRAME))
        entries.append(_shadow_entry(
            market="US", symbol=symbol, timeframe=US_TIMEFRAME,
            source="CLOUD_OPEND",
            reader_status=us_status, observed_bar_count=bars,
            info=us_snapshot, now=now,
            process_healthy="PASS" if health_status == "HEALTHY" else "UNKNOWN",
            # Callback processing timing is NOT provider network/ingestion RTT.
            latency_ms=None,
        ))

    for symbol in CN_SYMBOLS:
        info = cn_reads.get(symbol)
        info = info if isinstance(info, dict) else {}
        provenance = info.get("provider_used")
        provider = (
            "TENCENT" if provenance == "tencent" else
            "EASTMONEY" if provenance == "eastmoney" else None
        )
        entries.append(_shadow_entry(
            market="CN", symbol=symbol, timeframe=CN_TIMEFRAME, source=provider,
            reader_status=_safe_status(info.get("status")),
            observed_bar_count=_count(info.get("total_row_count")),
            info=info, now=now,
            # REST path elapsed time is one observation, not a P95 network SLO.
            latency_ms=_finite_number(info.get("provider_request_latency_ms")),
        ))

    assert len(entries) == len(US_SYMBOLS) + len(CN_SYMBOLS)
    assert all(row["decision"]["decision"] == "BLOCKED" for row in entries)
    return {
        "schema": "stock_razor_data_fabric_aws_shadow_witness_v0_1",
        "observed_at_utc": now.astimezone(timezone.utc).isoformat(),
        "scope": "AWS_EXISTING_READ_ONLY_CACHE_WITH_UNQUALIFIED_SOURCES",
        "us_livefeed_health": health_status,
        "us_snapshot_status": us_status,
        "entries": entries,
        "proposals_admitted": 0,
        "sources_proven_qualified": 0,
        "source_arbiter_runtime_admission": "BLOCKED",
        "off_pc_independent_market_acquisition": "NOT_VERIFIED",
        "data_qualification": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "can_confirm_signal": False,
        "live_trade": False,
        "canonical_writer_created": False,
    }


def main() -> int:
    from data_provider.cn_cloud_runtime_reader import read_cn_market_data
    from data_provider.us_canonical_runtime_reader import (
        read_us_livefeed_health, read_us_market_snapshots,
    )

    now = datetime.now(timezone.utc)
    try:
        report = audit_cloud_shadow(
            us_health=read_us_livefeed_health(now_utc=now),
            us_snapshot=read_us_market_snapshots(US_SYMBOLS, now_utc=now),
            cn_reads={
                symbol: read_cn_market_data(symbol, timeframe=CN_TIMEFRAME, limit=1, now_utc=now)
                for symbol in CN_SYMBOLS
            },
            now=now,
        )
        print(json.dumps(report, ensure_ascii=True, sort_keys=True))
        return 0
    except Exception as exc:
        # Never surface provider payloads, URL, raw error or credentials.
        print(json.dumps({
            "schema": "stock_razor_data_fabric_aws_shadow_witness_v0_1",
            "probe_status": "FAILED",
            "failure_class": type(exc).__name__,
            "source_arbiter_runtime_admission": "BLOCKED",
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""AWS US/CN source selection SHADOW witness; exclusively existing cache reads.

No provider sockets, new subscriptions, canonical writes, service restarts,
trading or qualification promotions. Missing independent evidence stays UNKNOWN.
"""
from __future__ import annotations

from datetime import datetime, timezone
import argparse
import re
import time
import json
from math import isfinite
from typing import Any, Callable

from src.services.data_fabric_source_arbiter_policy import (
    Candidate,
    propose_authoritative_source,
)
from src.services.live_feed.futu_k1m_currentness import (
    futu_us_market_state_to_session,
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



_BAR_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?$")


def _bar_label(info: dict) -> str | None:
    rows = info.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    last = rows[-1]
    value = last.get("label") if isinstance(last, dict) else None
    return value if isinstance(value, str) and _BAR_TIME.fullmatch(value) else None


def _increment(previous: object, current: object) -> str:
    a, b = _count(previous), _count(current)
    if a is None or b is None:
        return "UNKNOWN"
    if b < a:
        return "COUNTER_RESET_OR_REORDERED"
    return "ADVANCED" if b > a else "UNCHANGED"


def _sample_progress_evidence(
    *,
    us_health: dict, us_snapshot: dict, cn_reads: dict,
) -> dict:
    # Use the existing OpenD session mapping; generic OPEN/PRE_MARKET enums
    # are not the provider's states and must never manufacture a session.
    raw_market_state = us_health.get("market_state_us")
    market_state = (
        raw_market_state.strip().upper()
        if isinstance(raw_market_state, str) else "UNKNOWN"
    )
    market_session = futu_us_market_state_to_session(market_state)
    return {
        "us": {
            "health_status": _safe_status(us_health.get("status")),
            "market_state": market_state if market_session != "unknown" else "UNKNOWN",
            "market_session": market_session,
            "heartbeat_sequence": _count(us_health.get("sequence")),
            "received_events": _count(us_health.get("event_count")),
            "accepted_events": _count(us_health.get("accepted_event_count")),
            "canonical_sequence": _count(us_snapshot.get("sequence")),
            "canonical_export_status": _safe_status(us_health.get("canonical_export_status")),
            "canonical_snapshot_status": _safe_status(us_snapshot.get("status")),
            "canonical_snapshot_age_seconds": _finite_number(
                us_snapshot.get("source_age_seconds")
            ),
        },
        "cn": {
            symbol: {
                "reader_status": _safe_status((cn_reads.get(symbol) or {}).get("status")),
                "poll_sequence": _count((cn_reads.get(symbol) or {}).get("sequence")),
                "last_bar_label": _bar_label(cn_reads.get(symbol) or {}),
                "reported_provider": (cn_reads.get(symbol) or {}).get("provider_used")
                if (cn_reads.get(symbol) or {}).get("provider_used") in {
                    "eastmoney", "tencent"
                } else "UNKNOWN",
            }
            for symbol in CN_SYMBOLS
        },
    }


def observe_source_progress(before: dict, after: dict, *, interval_seconds: float) -> dict:
    """Compare two independently timed cache reads, not inferred unique feed RTT.

    We can establish whether cached counters *changed*, not whether all source
    events arrived, network/entitlement quality or real-time qualification.
    """
    if not isinstance(interval_seconds, (int, float)) or isinstance(interval_seconds, bool) or not 0 < interval_seconds <= 30:
        raise ValueError("interval must be (0,30] seconds")
    first, last = before.get("us", {}), after.get("us", {})
    us = {
        "market_state": last.get("market_state", "UNKNOWN"),
        "market_session": last.get("market_session", "unknown"),
        "health": last.get("health_status", "UNKNOWN"),
        "heartbeat_sequence": _increment(first.get("heartbeat_sequence"), last.get("heartbeat_sequence")),
        "received_event_counter": _increment(first.get("received_events"), last.get("received_events")),
        "accepted_event_counter": _increment(first.get("accepted_events"), last.get("accepted_events")),
        "canonical_snapshot_sequence": _increment(first.get("canonical_sequence"), last.get("canonical_sequence")),
        "canonical_export_status": last.get("canonical_export_status", "UNKNOWN"),
        "canonical_snapshot_status": last.get("canonical_snapshot_status", "UNKNOWN"),
        "canonical_snapshot_age_seconds": last.get("canonical_snapshot_age_seconds"),
    }
    if us["accepted_event_counter"] == "ADVANCED":
        status = "ACCEPTED_COUNTER_ADVANCED_UNQUALIFIED"
    elif us["accepted_event_counter"] == "COUNTER_RESET_OR_REORDERED":
        status = "COUNTER_RESET_OR_REORDERED"
    elif us["accepted_event_counter"] == "UNCHANGED" and us["market_session"] == "closed":
        status = "CLOSED_SESSION_NO_ADVANCEMENT_NOT_FAILURE"
    elif us["accepted_event_counter"] == "UNCHANGED" and us["market_session"] in {
        "premarket", "afterhours", "overnight"
    }:
        status = "NON_REGULAR_SESSION_NO_ADVANCEMENT_NOT_FAILURE"
    else:
        status = "EVENT_PROGRESS_NOT_VERIFIED"
    us["event_progress_classification"] = status
    # This is a *triage label*, not a causal finding or a latency sample.
    # A completed bar can remain unchanged even after accepted callbacks.
    if us["canonical_export_status"] != "PASS":
        chain = "EXPORT_NOT_CONFIRMED"
    elif us["canonical_snapshot_status"] == "STALE":
        chain = "EXPORT_PASS_SNAPSHOT_STALE_CAUSE_UNKNOWN"
    elif (us["accepted_event_counter"] == "ADVANCED"
          and us["canonical_snapshot_sequence"] == "UNCHANGED"):
        chain = "ACCEPTED_CALLBACKS_SNAPSHOT_UNCHANGED_CAUSE_UNKNOWN"
    elif (us["accepted_event_counter"] == "ADVANCED"
          and us["canonical_snapshot_sequence"] == "ADVANCED"):
        chain = "BOTH_COUNTERS_ADVANCED_UNQUALIFIED"
    else:
        chain = "CANONICAL_PROGRESSION_NOT_VERIFIED"
    us["canonical_chain_classification"] = chain

    cn = {}
    left, right = before.get("cn", {}), after.get("cn", {})
    for symbol in CN_SYMBOLS:
        a, b = left.get(symbol, {}), right.get(symbol, {})
        prev, current = a.get("last_bar_label"), b.get("last_bar_label")
        if a.get("reported_provider") != b.get("reported_provider"):
            label_status = "SOURCE_SWITCH_UNQUALIFIED"
        elif prev is None or current is None:
            label_status = "UNKNOWN"
        else:
            label_status = "CHANGED_UNQUALIFIED" if current != prev else "UNCHANGED"
        cn[symbol] = {
            "reader_status": b.get("reader_status", "UNKNOWN"),
            "provider": b.get("reported_provider", "UNKNOWN"),
            "observer_poll_sequence": _increment(a.get("poll_sequence"), b.get("poll_sequence")),
            "15m_last_bar_label": label_status,
            "provider_event_progress": "NOT_VERIFIED",
        }

    return {
        "measurement_scope": "TWO_SEPARATE_AWS_CACHE_READS_NOT_PROVIDER_SLO",
        "interval_seconds": float(interval_seconds),
        "us": us,
        "cn": cn,
        "unique_provider_event_delivery_qualified": False,
        "cloud_off_pc_independence": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }



def main() -> int:
    from data_provider.cn_cloud_runtime_reader import read_cn_market_data
    from data_provider.us_canonical_runtime_reader import (
        read_us_livefeed_health, read_us_market_snapshots,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--progress-interval-seconds", type=float, default=12.0)
    args = parser.parse_args()
    if not 0 < args.progress_interval_seconds <= 30:
        raise SystemExit("progress interval must be (0,30] seconds")

    def read_observation():
        instant = datetime.now(timezone.utc)
        return (
            instant,
            read_us_livefeed_health(now_utc=instant),
            read_us_market_snapshots(US_SYMBOLS, now_utc=instant),
            {
                symbol: read_cn_market_data(symbol, timeframe=CN_TIMEFRAME, limit=1, now_utc=instant)
                for symbol in CN_SYMBOLS
            },
        )

    try:
        first_time, first_health, first_us, first_cn = read_observation()
        first = _sample_progress_evidence(
            us_health=first_health, us_snapshot=first_us, cn_reads=first_cn,
        )
        time.sleep(args.progress_interval_seconds)
        now, us_health, us_snapshot, cn_reads = read_observation()
        second = _sample_progress_evidence(
            us_health=us_health, us_snapshot=us_snapshot, cn_reads=cn_reads,
        )
        report = audit_cloud_shadow(
            us_health=us_health,
            us_snapshot=us_snapshot,
            cn_reads=cn_reads,
            now=now,
        )
        report["source_progress"] = observe_source_progress(
            first, second,
            interval_seconds=(now-first_time).total_seconds(),
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

"""Offline market-event-to-notification latency evidence, never an execution gate.

No provider, broker, network, notification, or AWS operations are performed.
Unique event sequences are mandatory: repeated reads of one cached event must
not be counted as independent samples.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Mapping

MAX_TRACES = 1000
MIN_DISTRIBUTION = 30
MAX_CLOCK_ERROR_MS = 10.0
MAX_CHAIN_MS = 120_000.0
STAGES = (
    "provider_event_utc",
    "aws_ingest_utc",
    "radar_complete_utc",
    "notification_dispatch_utc",
    "notification_receipt_utc",
)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo), 3)


def _valid_time(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _span_ms(first: datetime, last: datetime) -> float:
    return (last.astimezone(timezone.utc) - first.astimezone(timezone.utc)).total_seconds() * 1000


def audit_market_to_notification_traces(
    traces: list[Mapping[str, object]],
    *,
    min_samples: int = MIN_DISTRIBUTION,
) -> dict:
    """Summarize independently identified stage traces with clock-error guards.

    Caller must independently establish source event timestamp provenance,
    cross-host clock synchronization, and actual phone/device receipt. This
    function never asserts those claims from the mere presence of timestamps.
    """
    base = {
        "schema": "stock_razor_notification_latency_audit_v0_1",
        "research_only": True,
        "provider_requests": 0,
        "notification_sends": 0,
        "execution_permission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "data_qualification": "NOT_VERIFIED",
        "latency_slo_qualified": False,
    }

    def blocked(reason: str) -> dict:
        return {**base, "status": "BLOCKED", "reason": reason,
                "accepted_unique_events": 0, "distributions": {}}

    if (not isinstance(traces, list) or len(traces) > MAX_TRACES
            or type(min_samples) is not int or not 30 <= min_samples <= MAX_TRACES):
        return blocked("INVALID_BOUNDS")

    seen: set[tuple[str, int]] = set()
    duplicates = 0
    rejected = 0
    receipt_missing = 0
    spans: dict[str, list[float]] = {
        "provider_to_aws_ms": [],
        "aws_to_radar_ms": [],
        "radar_to_dispatch_ms": [],
        "dispatch_to_receipt_ms": [],
        "provider_to_receipt_ms": [],
    }
    accepted = 0
    for trace in traces:
        if not isinstance(trace, Mapping):
            rejected += 1
            continue
        runtime = trace.get("source_runtime_id")
        sequence = trace.get("source_sequence")
        if (not isinstance(runtime, str) or not 1 <= len(runtime) <= 128
                or type(sequence) is not int or sequence < 1):
            rejected += 1
            continue
        identity = (runtime, sequence)
        if identity in seen:
            duplicates += 1
            continue
        if (trace.get("provider_timestamp_verified") is not True
                or trace.get("clock_sync_verified") is not True):
            rejected += 1
            continue
        uncertainty = trace.get("max_cross_host_clock_error_ms")
        if (type(uncertainty) not in (int, float) or not isfinite(uncertainty)
                or not 0 <= uncertainty <= MAX_CLOCK_ERROR_MS):
            rejected += 1
            continue
        if any(not _valid_time(trace.get(stage)) for stage in STAGES[:-1]):
            rejected += 1
            continue
        receipt = trace.get("notification_receipt_utc")
        if receipt is not None and (
            not _valid_time(receipt)
            or trace.get("device_receipt_verified") is not True
        ):
            # Dispatch/HTTP 200/queue acceptance is not phone delivery.
            rejected += 1
            continue
        times = [trace[stage] for stage in STAGES[:-1]]
        if receipt is not None:
            times.append(receipt)
        # A clock discrepancy within declared error can be an apparent
        # negative span. Never silently clamp it to zero.
        intervals = [_span_ms(a, b) for a, b in zip(times, times[1:])]
        if any(not isfinite(x) or x < 0 or x > MAX_CHAIN_MS for x in intervals):
            rejected += 1
            continue
        if _span_ms(times[0], times[-1]) > MAX_CHAIN_MS:
            rejected += 1
            continue
        seen.add(identity)
        accepted += 1
        spans["provider_to_aws_ms"].append(intervals[0])
        spans["aws_to_radar_ms"].append(intervals[1])
        spans["radar_to_dispatch_ms"].append(intervals[2])
        if receipt is not None:
            spans["dispatch_to_receipt_ms"].append(intervals[3])
            spans["provider_to_receipt_ms"].append(_span_ms(times[0], receipt))
        else:
            receipt_missing += 1
    distributions = {
        name: {
            "sample_count": len(values),
            "p50_ms": _percentile(values, .5) if len(values) >= min_samples else None,
            "p95_ms": _percentile(values, .95) if len(values) >= min_samples else None,
            "max_ms": round(max(values), 3) if len(values) >= min_samples else None,
            "distribution_ready": len(values) >= min_samples,
        }
        for name, values in spans.items()
    }
    return {
        **base, "status": "OBSERVATIONAL_ONLY",
        "input_traces": len(traces),
        "accepted_unique_events": accepted,
        "duplicate_sequences_skipped": duplicates,
        "invalid_or_unqualified_skipped": rejected,
        "missing_receipt_events": receipt_missing,
        "min_distribution_samples": min_samples,
        "distributions": distributions,
        "next_gate": "VERIFY_SOURCE_PROVENANCE_CLOCK_SYNC_RECEIPT_AND_MARKET_HOURS",
    }

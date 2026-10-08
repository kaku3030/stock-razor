"""Unified fail-closed telemetry for STOCK RAZOR cloud fast-path measurements.

This module measures and summarizes performance evidence only.  It never
promotes Data Admission, Radar Admission, signal confirmation, or execution.
Missing timing/quality evidence remains explicit instead of being inferred from
another layer's latency.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from math import floor
from typing import Iterable


CANONICAL_READ_SLO_MS = 300.0
RADAR_ANALYSIS_SLO_MS = 500.0
DATA_TO_RADAR_SLO_MS = 1000.0

_LATENCY_FIELDS = (
    "provider_latency_ms",
    "canonical_latency_ms",
    "radar_analysis_latency_ms",
    "radar_read_latency_ms",
    "mcp_latency_ms",
    "chatgpt_access_latency_ms",
    "e2e_latency_ms",
)


@dataclass(frozen=True)
class FastPathSample:
    sample_id: str
    market: str
    observed_at: datetime
    provider: str | None = None
    provider_latency_ms: float | None = None
    canonical_latency_ms: float | None = None
    radar_analysis_latency_ms: float | None = None
    radar_read_latency_ms: float | None = None
    data_to_radar_latency_ms: float | None = None
    mcp_latency_ms: float | None = None
    chatgpt_access_latency_ms: float | None = None
    e2e_latency_ms: float | None = None
    freshness_ms: float | None = None
    success: bool = False
    retry_count: int = 0
    fallback_count: int = 0
    fallback_provider: str | None = None
    freshness_state: str = "UNKNOWN"
    data_completeness: str = "UNKNOWN"
    data_correctness_state: str = "UNKNOWN"
    analysis_quality_state: str = "UNKNOWN"
    repo_sha: str | None = None
    runtime_instance_id: str | None = None
    radar_admission: str = "BLOCKED"
    live_trade: bool = False
    can_confirm_signal: bool = False

    def __post_init__(self) -> None:
        if self.market not in {"us", "cn"}:
            raise ValueError("market must be 'us' or 'cn'")
        if not self.sample_id.strip():
            raise ValueError("sample_id is required")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        for field in (*_LATENCY_FIELDS, "data_to_radar_latency_ms", "freshness_ms"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, (int, float)) or value < 0):
                raise ValueError(f"{field} must be non-negative or None")
        if self.retry_count < 0 or self.fallback_count < 0:
            raise ValueError("retry/fallback counts must be non-negative")
        if self.radar_admission != "BLOCKED":
            raise ValueError("performance evidence cannot promote Radar admission")
        if self.live_trade:
            raise ValueError("performance evidence cannot enable live trading")
        if self.can_confirm_signal:
            raise ValueError("performance evidence cannot confirm signals")

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["observed_at"] = self.observed_at.isoformat()
        return payload


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percentile
    lower = floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def _metric_summary(samples: list[FastPathSample], field: str) -> dict:
    values = [
        float(value)
        for sample in samples
        if (value := getattr(sample, field)) is not None
    ]
    return {
        "sample_count": len(values),
        "missing_count": len(samples) - len(values),
        "p50_ms": _percentile(values, 0.50),
        "p95_ms": _percentile(values, 0.95),
        "p99_ms": _percentile(values, 0.99),
        "min_ms": round(min(values), 3) if values else None,
        "max_ms": round(max(values), 3) if values else None,
    }


def sample_quality_state(
    sample: FastPathSample,
    *,
    freshness_limit_ms: float | None,
) -> str:
    """Return PASS/FAIL/UNKNOWN for measurement quality only.

    This is not Data Admission or Radar Admission.
    """

    if not sample.success:
        return "FAIL"
    states = (
        sample.freshness_state,
        sample.data_completeness,
        sample.data_correctness_state,
        sample.analysis_quality_state,
    )
    if any(state in {"FAIL", "BLOCKED", "STALE", "INVALID"} for state in states):
        return "FAIL"
    if freshness_limit_ms is None or sample.freshness_ms is None:
        return "UNKNOWN"
    if sample.freshness_ms > freshness_limit_ms:
        return "FAIL"
    if any(state != "PASS" for state in states):
        return "UNKNOWN"
    return "PASS"


def sample_slo_state(sample: FastPathSample) -> str:
    """Evaluate only the documented internal performance SLOs."""

    required = (
        sample.canonical_latency_ms,
        sample.radar_analysis_latency_ms,
        sample.data_to_radar_latency_ms,
    )
    if any(value is None for value in required):
        return "UNKNOWN"
    if (
        sample.canonical_latency_ms >= CANONICAL_READ_SLO_MS
        or sample.radar_analysis_latency_ms >= RADAR_ANALYSIS_SLO_MS
        or sample.data_to_radar_latency_ms >= DATA_TO_RADAR_SLO_MS
    ):
        return "FAIL"
    return "PASS"


def summarize_fast_path(samples: Iterable[FastPathSample]) -> dict:
    rows = list(samples)
    if not rows:
        return {
            "sample_count": 0,
            "status": "INSUFFICIENT_EVIDENCE",
            "radar_admission": "BLOCKED",
            "live_trade": False,
            "can_confirm_signal": False,
            "metrics": {},
        }

    metrics = {
        field: _metric_summary(rows, field)
        for field in (*_LATENCY_FIELDS, "data_to_radar_latency_ms", "freshness_ms")
    }
    successful = sum(sample.success for sample in rows)
    retried = sum(sample.retry_count > 0 for sample in rows)
    fallback = sum(sample.fallback_count > 0 for sample in rows)
    markets = tuple(sorted({sample.market for sample in rows}))
    providers = tuple(sorted({sample.provider for sample in rows if sample.provider}))

    required_evidence_missing = any(
        metrics[field]["missing_count"] > 0
        for field in (
            "provider_latency_ms",
            "canonical_latency_ms",
            "radar_analysis_latency_ms",
            "data_to_radar_latency_ms",
            "mcp_latency_ms",
            "e2e_latency_ms",
            "freshness_ms",
        )
    )
    status = "EVIDENCE_COMPLETE" if not required_evidence_missing else "INCOMPLETE_EVIDENCE"

    return {
        "sample_count": len(rows),
        "status": status,
        "markets": markets,
        "providers": providers,
        "success_rate": round(successful / len(rows), 6),
        "retry_rate": round(retried / len(rows), 6),
        "fallback_rate": round(fallback / len(rows), 6),
        "metrics": metrics,
        "slo": {
            "canonical_read_ms": CANONICAL_READ_SLO_MS,
            "radar_analysis_ms": RADAR_ANALYSIS_SLO_MS,
            "data_to_radar_ms": DATA_TO_RADAR_SLO_MS,
        },
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "can_confirm_signal": False,
    }

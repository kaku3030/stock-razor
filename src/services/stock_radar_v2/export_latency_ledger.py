"""Bounded, unique Canonical-export-sequence timing diagnostics.

One sample requires one new, validated source export sequence. This metric
begins AFTER the producer writes its canonical export; it is explicitly NOT
a provider callback, market-event, trade-fill, or end-to-end latency sample.
Fail-closed: observations never authorize radar admission or live trading.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from math import isfinite


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return round(
        ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower),
        3,
    )


class CanonicalExportLatencyLedger:
    """Track distinct validated export sequences in a finite local time window."""

    def __init__(
        self,
        *,
        max_samples: int = 128,
        horizon_seconds: int = 1200,
        min_distribution_samples: int = 20,
        max_export_to_radar_ms: float = 120_000.0,
    ):
        if max_samples < 1 or horizon_seconds < 1 or min_distribution_samples < 1:
            raise ValueError("sample capacity, horizon, and distribution minimum must be positive")
        if not isfinite(max_export_to_radar_ms) or max_export_to_radar_ms <= 0:
            raise ValueError("max_export_to_radar_ms must be positive and finite")
        self._samples = deque(maxlen=max_samples)
        self._horizon = timedelta(seconds=horizon_seconds)
        self._min_distribution_samples = min_distribution_samples
        self._max_export_to_radar_ms = max_export_to_radar_ms
        self._identity: tuple[str, str] | None = None
        self._last_sequence: int | None = None
        self._cold_start_baselines = 0
        self._stale_export_skips = 0

    def _prune(self, now: datetime) -> None:
        cutoff = now - self._horizon
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def observe(
        self,
        *,
        source_repo_sha: str,
        source_runtime_id: str | None,
        source_sequence: int | None,
        export_to_radar_ms: float | None,
        analysis_ms: float | None,
        observed_at: datetime,
    ) -> bool:
        """Return True only for a new, finite, valid Canonical export observation."""
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return False
        if not source_repo_sha or not source_runtime_id:
            return False
        if isinstance(source_sequence, bool) or not isinstance(source_sequence, int) or source_sequence <= 0:
            return False
        if (
            isinstance(export_to_radar_ms, bool)
            or not isinstance(export_to_radar_ms, (int, float))
            or not isfinite(export_to_radar_ms)
            or export_to_radar_ms < 0
            or isinstance(analysis_ms, bool)
            or not isinstance(analysis_ms, (int, float))
            or not isfinite(analysis_ms)
            or analysis_ms < 0
        ):
            return False
        identity = (source_repo_sha, source_runtime_id)
        if self._identity != identity:
            # Starting a Worker or restarting the Producer can expose a
            # much older cached export. Observing it for the first time is
            # NOT a new publication; use only as a baseline.
            self._samples.clear()
            self._identity = identity
            self._last_sequence = source_sequence
            self._cold_start_baselines += 1
            return False
        if self._last_sequence is not None and source_sequence <= self._last_sequence:
            return False
        # A new sequence is necessary, but not sufficient: ignore old exports
        # observed after downtime or while the market is closed. Do not
        # transform a 72-minute-old export into a spurious P95/P99.
        self._last_sequence = source_sequence
        if export_to_radar_ms > self._max_export_to_radar_ms:
            self._stale_export_skips += 1
            return False
        timestamp = observed_at.astimezone(timezone.utc)
        self._prune(timestamp)
        self._samples.append((timestamp, source_sequence, float(export_to_radar_ms), float(analysis_ms)))
        return True

    def summary(self, *, as_of: datetime) -> dict:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        self._prune(as_of.astimezone(timezone.utc))
        export_values = [row[2] for row in self._samples]
        analysis_values = [row[3] for row in self._samples]

        def stats(values: list[float]) -> dict:
            return {
                "p50_ms": _percentile(values, 0.5),
                "p95_ms": _percentile(values, 0.95),
                "p99_ms": _percentile(values, 0.99),
                "max_ms": round(max(values), 3) if values else None,
            }

        distribution_ready = len(self._samples) >= self._min_distribution_samples
        return {
            "scope": "CANONICAL_EXPORT_TO_RADAR_NOT_PROVIDER_EVENT_E2E",
            "unique_source_export_sequences": len(self._samples),
            "min_distribution_samples": self._min_distribution_samples,
            "distribution_ready": distribution_ready,
            "cold_start_baselines_skipped": self._cold_start_baselines,
            "stale_export_sequences_skipped": self._stale_export_skips,
            "source_runtime_instance_id": self._identity[1] if self._identity else None,
            "last_source_sequence": self._samples[-1][1] if self._samples else None,
            "last_observed_at_utc": self._samples[-1][0].isoformat() if self._samples else None,
            "canonical_export_to_radar_completion": (
                stats(export_values) if distribution_ready else {
                    "p50_ms": _percentile(export_values, 0.5),
                    "p95_ms": None,
                    "p99_ms": None,
                    "max_ms": round(max(export_values), 3) if export_values else None,
                }
            ),
            "radar_poll_and_analysis": (
                stats(analysis_values) if distribution_ready else {
                    "p50_ms": _percentile(analysis_values, 0.5),
                    "p95_ms": None,
                    "p99_ms": None,
                    "max_ms": round(max(analysis_values), 3) if analysis_values else None,
                }
            ),
            "market_event_sample_count": 0,
            "provider_to_radar_e2e": "NOT_VERIFIED",
            "slo_qualified": False,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }

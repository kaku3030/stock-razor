from datetime import datetime, timezone

import pytest

from src.services.cloud_fast_path_metrics import (
    FastPathSample,
    sample_quality_state,
    sample_slo_state,
    summarize_fast_path,
)


NOW = datetime(2026, 10, 8, 5, 0, tzinfo=timezone.utc)


def sample(**overrides):
    values = {
        "sample_id": "s1",
        "market": "us",
        "observed_at": NOW,
        "provider": "futu-opend",
        "provider_latency_ms": 100,
        "canonical_latency_ms": 20,
        "radar_analysis_latency_ms": 200,
        "radar_read_latency_ms": 4,
        "data_to_radar_latency_ms": 400,
        "mcp_latency_ms": 30,
        "e2e_latency_ms": 900,
        "freshness_ms": 500,
        "success": True,
        "freshness_state": "PASS",
        "data_completeness": "PASS",
        "data_correctness_state": "PASS",
        "analysis_quality_state": "PASS",
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "can_confirm_signal": False,
    }
    values.update(overrides)
    return FastPathSample(**values)


def test_full_measured_sample_can_pass_performance_and_quality_without_admission():
    item = sample()
    assert sample_slo_state(item) == "PASS"
    assert sample_quality_state(item, freshness_limit_ms=1000) == "PASS"
    assert item.radar_admission == "BLOCKED"
    assert item.live_trade is False
    assert item.can_confirm_signal is False


def test_missing_radar_compute_latency_stays_unknown_not_pass():
    item = sample(radar_analysis_latency_ms=None)
    assert sample_slo_state(item) == "UNKNOWN"
    summary = summarize_fast_path([item])
    assert summary["status"] == "INCOMPLETE_EVIDENCE"
    assert summary["metrics"]["radar_analysis_latency_ms"]["missing_count"] == 1


def test_radar_read_latency_cannot_substitute_for_analysis_latency():
    item = sample(radar_analysis_latency_ms=None, radar_read_latency_ms=0.1)
    assert sample_slo_state(item) == "UNKNOWN"


def test_fast_stale_data_fails_quality_gate():
    item = sample(freshness_ms=5000, canonical_latency_ms=1)
    assert sample_quality_state(item, freshness_limit_ms=1000) == "FAIL"


def test_unknown_quality_never_promotes_to_pass():
    item = sample(data_correctness_state="UNKNOWN")
    assert sample_quality_state(item, freshness_limit_ms=1000) == "UNKNOWN"


def test_slo_boundaries_are_strict():
    assert sample_slo_state(sample(canonical_latency_ms=300)) == "FAIL"
    assert sample_slo_state(sample(radar_analysis_latency_ms=500)) == "FAIL"
    assert sample_slo_state(sample(data_to_radar_latency_ms=1000)) == "FAIL"


def test_summary_reports_percentiles_and_rates():
    rows = [
        sample(sample_id="a", canonical_latency_ms=10, retry_count=0, fallback_count=0),
        sample(sample_id="b", canonical_latency_ms=20, retry_count=1, fallback_count=0),
        sample(sample_id="c", canonical_latency_ms=30, retry_count=0, fallback_count=1),
    ]
    summary = summarize_fast_path(rows)
    metric = summary["metrics"]["canonical_latency_ms"]
    assert metric["sample_count"] == 3
    assert metric["missing_count"] == 0
    assert metric["p50_ms"] == 20
    assert metric["p95_ms"] == 29
    assert summary["retry_rate"] == pytest.approx(1 / 3, abs=1e-6)
    assert summary["fallback_rate"] == pytest.approx(1 / 3, abs=1e-6)
    assert summary["radar_admission"] == "BLOCKED"


@pytest.mark.parametrize(
    "overrides",
    [
        {"provider_latency_ms": -1},
        {"retry_count": -1},
        {"radar_admission": "PASS"},
        {"live_trade": True},
        {"can_confirm_signal": True},
    ],
)
def test_invalid_or_unsafe_samples_fail_closed(overrides):
    with pytest.raises(ValueError):
        sample(**overrides)


def test_empty_window_is_insufficient_evidence():
    summary = summarize_fast_path([])
    assert summary["status"] == "INSUFFICIENT_EVIDENCE"
    assert summary["radar_admission"] == "BLOCKED"


def test_missing_retry_and_fallback_evidence_is_not_zero():
    summary = summarize_fast_path([sample(retry_count=None, fallback_count=None)])
    assert summary["retry_rate"] is None
    assert summary["retry_rate_sample_count"] == 0
    assert summary["retry_rate_missing_count"] == 1
    assert summary["fallback_rate"] is None
    assert summary["fallback_rate_sample_count"] == 0
    assert summary["fallback_rate_missing_count"] == 1

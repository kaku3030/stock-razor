from datetime import datetime, timedelta, timezone

from src.services.stock_radar_v2.export_latency_ledger import CanonicalExportLatencyLedger

NOW = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)


def observe(ledger, seq, *, delay=120.0, analysis=20.0, now=NOW, runtime="runtime-a"):
    return ledger.observe(
        source_repo_sha="a" * 40,
        source_runtime_id=runtime,
        source_sequence=seq,
        export_to_radar_ms=delay,
        analysis_ms=analysis,
        observed_at=now,
    )


def test_unique_export_sequence_not_repeated_poll():
    ledger = CanonicalExportLatencyLedger()
    assert observe(ledger, 7)
    assert not observe(ledger, 7)
    assert not observe(ledger, 6)
    summary = ledger.summary(as_of=NOW)
    assert summary["unique_source_export_sequences"] == 1
    assert summary["last_source_sequence"] == 7
    assert summary["canonical_export_to_radar_completion"]["p95_ms"] == 120
    assert summary["market_event_sample_count"] == 0
    assert summary["provider_to_radar_e2e"] == "NOT_VERIFIED"
    assert summary["slo_qualified"] is False
    assert summary["radar_admission"] == "BLOCKED"
    assert summary["live_trade"] is False


def test_percentiles_use_independent_sequences_not_cached_poll_replicas():
    ledger = CanonicalExportLatencyLedger()
    for i, ms in enumerate((100.0, 200.0, 300.0, 400.0), start=1):
        assert observe(ledger, i, delay=ms, analysis=ms / 2)
    p = ledger.summary(as_of=NOW)
    assert p["unique_source_export_sequences"] == 4
    assert p["canonical_export_to_radar_completion"]["p50_ms"] == 250
    assert p["canonical_export_to_radar_completion"]["p95_ms"] == 385
    assert p["canonical_export_to_radar_completion"]["p99_ms"] == 397
    assert p["radar_poll_and_analysis"]["p95_ms"] == 192.5


def test_source_restart_resets_histogram_and_no_promotion():
    ledger = CanonicalExportLatencyLedger()
    assert observe(ledger, 800)
    assert observe(ledger, 1, runtime="new")
    p = ledger.summary(as_of=NOW)
    assert p["unique_source_export_sequences"] == 1
    assert p["source_runtime_instance_id"] == "new"
    assert p["last_source_sequence"] == 1
    assert p["slo_qualified"] is False


def test_invalid_future_nan_negative_or_missing_observation_is_ignored():
    ledger = CanonicalExportLatencyLedger()
    assert not observe(ledger, 1, delay=float("nan"))
    assert not observe(ledger, 1, delay=-5)
    assert not observe(ledger, 1, analysis=float("inf"))
    assert not observe(ledger, 1, runtime="")
    assert not observe(ledger, 0)
    assert not observe(ledger, True)
    assert not observe(ledger, 1, now=NOW.replace(tzinfo=None))
    assert ledger.summary(as_of=NOW)["unique_source_export_sequences"] == 0


def test_samples_expire_and_memory_stays_bounded():
    ledger = CanonicalExportLatencyLedger(max_samples=3, horizon_seconds=10)
    for i in range(5):
        assert observe(ledger, i + 1, now=NOW + timedelta(seconds=i))
    assert ledger.summary(as_of=NOW + timedelta(seconds=4))["unique_source_export_sequences"] == 3
    late = ledger.summary(as_of=NOW + timedelta(seconds=30))
    assert late["unique_source_export_sequences"] == 0
    assert late["canonical_export_to_radar_completion"]["p99_ms"] is None


def test_only_sane_positive_configuration():
    import pytest
    with pytest.raises(ValueError):
        CanonicalExportLatencyLedger(max_samples=0)
    with pytest.raises(ValueError):
        CanonicalExportLatencyLedger(horizon_seconds=0)

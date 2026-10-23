from datetime import datetime, timedelta, timezone
import json

from data_provider.us_radar_runtime_reader import read_us_radar_analysis


NOW = datetime(2026, 10, 7, 6, 40, tzinfo=timezone.utc)


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _state(symbol, trend):
    return {
        "symbol": symbol,
        "status": "RESEARCH_STATE",
        "technical_state": {
            "symbol": symbol,
            "signal_permission": "record_only",
            "daily": {"trend": trend},
            "hourly": {"trend": trend},
            "intraday_15m": {"trend": trend},
        },
        "reasons": [],
    }


def _payload(*, emitted_at=NOW - timedelta(seconds=5), safe=True):
    return {
        "type": "us_radar_research_heartbeat",
        "runtime_instance_id": "radar-1",
        "worker_repo_sha": "a" * 40,
        "expected_source_repo_sha": "b" * 40,
        "host_id": "host",
        "sequence": 9,
        "emitted_at_utc": emitted_at.isoformat(),
        "source_path": "/run/source.json",
        "poll_status": "PASS",
        "evaluation": {
            "status": "PASS",
            "source_repo_sha": "b" * 40,
            "runtime_instance_id": "source-1",
            "source_sequence": 3,
            "source_emitted_at": (NOW - timedelta(seconds=6)).isoformat(),
            "source_delivery_mode": "REALTIME",
            "source_bar_closure": "UNPROVEN",
            "source_radar_admission": "BLOCKED",
            "source_live_trade": False,
            "symbols": [
                _state("US.AMD", "bullish"),
                _state("US.NVDA", "neutral"),
            ],
            "reasons": [],
            "research_only": True,
            "can_confirm_signal": False,
            "admission_diagnostics": {
                "decision": "BLOCKED",
                "promotion_authorized": False,
                "delivery_mode_realtime": True,
                "bar_closure_proven": False,
                "source_radar_admission": "BLOCKED",
                "source_live_trade": False,
                "reasons": [
                    "SOURCE_BAR_CLOSURE_UNPROVEN",
                    "PROMOTION_NOT_AUTHORIZED",
                ],
            },
        },
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED" if safe else "ADMITTED",
        "live_trade": False,
    }


def test_reads_precomputed_analysis_without_recomputation(tmp_path):
    path = _write(tmp_path / "radar.json", _payload())

    result = read_us_radar_analysis(["AMD"], path=path, now_utc=NOW)

    assert result["ok"] is True
    assert result["status"] == "PASS"
    assert list(result["symbols"]) == ["US.AMD"]
    assert result["symbols"]["US.AMD"]["technical_state"]["daily"]["trend"] == "bullish"
    assert result["source_delivery_mode"] == "REALTIME"
    assert result["source_bar_closure"] == "UNPROVEN"
    assert result["admission_diagnostics"]["decision"] == "BLOCKED"
    assert result["read_latency_ms"] >= 0


def test_no_symbol_filter_returns_all_states(tmp_path):
    path = _write(tmp_path / "radar.json", _payload())

    result = read_us_radar_analysis(path=path, now_utc=NOW)

    assert set(result["symbols"]) == {"US.AMD", "US.NVDA"}
    assert result["missing_symbols"] == []


def test_missing_symbol_is_explicit_not_fabricated(tmp_path):
    path = _write(tmp_path / "radar.json", _payload())

    result = read_us_radar_analysis(["TSLA"], path=path, now_utc=NOW)

    assert result["ok"] is True
    assert result["symbols"] == {}
    assert result["missing_symbols"] == ["US.TSLA"]


def test_stale_worker_state_is_exposed_as_stale(tmp_path):
    path = _write(
        tmp_path / "radar.json",
        _payload(emitted_at=NOW - timedelta(minutes=2)),
    )

    result = read_us_radar_analysis(path=path, now_utc=NOW, max_age_seconds=30)

    assert result["ok"] is True
    assert result["status"] == "STALE"
    assert result["source_age_seconds"] == 120


def test_top_level_safety_contract_violation_blocks(tmp_path):
    path = _write(tmp_path / "radar.json", _payload(safe=False))

    result = read_us_radar_analysis(path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "INVALID"
    assert result["error"] == "SAFETY_CONTRACT_VIOLATION"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_invalid_symbol_rejected_fail_closed(tmp_path):
    path = _write(tmp_path / "radar.json", _payload())

    result = read_us_radar_analysis(["HK.00700"], path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "INVALID_ARGUMENT"
    assert result["error"] == "INVALID_SYMBOL"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_us_radar_reader_exposes_completed_analysis_telemetry(tmp_path):
    payload = _payload()
    payload["radar_analysis_performed"] = True
    payload["radar_analysis_latency_ms"] = 214.5
    payload["data_to_radar_latency_ms"] = 612.0
    path = _write(tmp_path / "radar.json", payload)

    result = read_us_radar_analysis(["AMD"], path=path, now_utc=NOW)

    assert result["status"] == "PASS"
    assert result["radar_analysis_performed"] is True
    assert result["radar_analysis_latency_ms"] == 214.5
    assert result["data_to_radar_latency_ms"] == 612.0
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_us_radar_reader_allows_legacy_missing_telemetry_as_unknown(tmp_path):
    path = _write(tmp_path / "radar.json", _payload())

    result = read_us_radar_analysis(path=path, now_utc=NOW)

    assert result["status"] == "PASS"
    assert result["radar_analysis_performed"] is None
    assert result["radar_analysis_latency_ms"] is None
    assert result["data_to_radar_latency_ms"] is None


def test_us_radar_reader_rejects_inconsistent_telemetry(tmp_path):
    payload = _payload()
    payload["radar_analysis_performed"] = False
    payload["radar_analysis_latency_ms"] = 0.1
    path = _write(tmp_path / "radar.json", payload)

    result = read_us_radar_analysis(path=path, now_utc=NOW)

    assert result["status"] == "INVALID"
    assert result["error"] == "RADAR_TELEMETRY_INCONSISTENT"
    assert result["radar_admission"] == "BLOCKED"


def test_source_mismatch_not_masked_by_fresh_heartbeat(tmp_path):
    payload = _payload()
    payload["evaluation"]["source_repo_sha"] = "c" * 40
    payload["evaluation"]["admission_diagnostics"]["reasons"].append(
        "SOURCE_REPO_SHA_MISMATCH"
    )
    result = read_us_radar_analysis(path=_write(tmp_path / "radar.json", payload), now_utc=NOW)

    assert result["status"] == "PASS"  # file freshness, NOT data qualification
    assert result["source_lineage_status"] == "MISMATCH"
    assert result["reported_source_repo_sha"] == "c" * 40
    assert result["expected_source_repo_sha"] == "b" * 40
    assert result["source_lineage_evidence_scope"] == (
        "WORKER_REPORTED_NOT_INDEPENDENT_LIVEFEED_CHECK"
    )
    assert result["radar_admission"] == "BLOCKED"
    assert result["can_confirm_signal"] is False


def test_matching_worker_report_never_implies_external_livefeed_match(tmp_path):
    result = read_us_radar_analysis(
        path=_write(tmp_path / "radar.json", _payload()), now_utc=NOW,
    )
    assert result["source_lineage_status"] == (
        "WORKER_DECLARED_MATCH_NOT_EXTERNAL_VERIFICATION"
    )
    assert result["radar_admission"] == "BLOCKED"


def test_invalid_or_missing_source_sha_is_unknown_not_match(tmp_path):
    payload = _payload()
    payload["evaluation"]["source_repo_sha"] = None
    result = read_us_radar_analysis(
        path=_write(tmp_path / "radar.json", payload), now_utc=NOW,
    )
    assert result["source_lineage_status"] == "UNKNOWN"
    assert result["radar_admission"] == "BLOCKED"


def test_self_reported_mismatch_diagnostic_vetoes_equal_revisions(tmp_path):
    payload = _payload()
    payload["evaluation"]["admission_diagnostics"]["reasons"].append(
        "SOURCE_REPO_SHA_MISMATCH"
    )
    result = read_us_radar_analysis(
        path=_write(tmp_path / "radar.json", payload), now_utc=NOW,
    )
    assert result["source_lineage_status"] == "MISMATCH"
    assert result["radar_admission"] == "BLOCKED"


def _unavailable_source_payload(tmp_path, source_content=None):
    from src.services.stock_radar_v2.canonical_snapshot_worker import (
        CanonicalSnapshotRadarWorker,
    )

    source_path = tmp_path / "canonical.json"
    if source_content is not None:
        source_path.write_text(source_content, encoding="utf-8")
    worker = CanonicalSnapshotRadarWorker(expected_repo_sha="b" * 40)
    evaluation = worker.poll_file(source_path).to_dict()
    payload = _payload()
    payload.update(
        evaluation=evaluation,
        poll_status=evaluation["status"],
        radar_analysis_performed=False,
    )
    return payload


def test_real_missing_source_worker_result_preserves_root_failure(tmp_path):
    payload = _unavailable_source_payload(tmp_path)
    path = _write(tmp_path / "radar.json", payload)

    result = read_us_radar_analysis(["QQQ"], path=path, now_utc=NOW)

    assert result["error"] == "SOURCE_UNAVAILABLE"
    assert result["status"] == "BLOCKED"
    assert result["ok"] is False
    assert result["source_reasons"] == ["SOURCE_INVALID:FileNotFoundError"]
    assert result["source_lineage_status"] == "UNKNOWN"
    assert result["source_radar_admission"] is None
    assert result["source_live_trade"] is None
    assert result["symbols"] == {}
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert result["can_confirm_signal"] is False


def test_real_corrupt_source_worker_result_preserves_root_failure(tmp_path):
    payload = _unavailable_source_payload(tmp_path, "{broken")
    path = _write(tmp_path / "radar.json", payload)

    result = read_us_radar_analysis(path=path, now_utc=NOW)

    assert result["error"] == "SOURCE_UNAVAILABLE"
    assert result["source_reasons"] == ["SOURCE_INVALID:JSONDecodeError"]
    assert result["status"] == "BLOCKED"
    assert result["source_radar_admission"] is None
    assert result["source_live_trade"] is None


def test_unavailable_source_never_hides_unsafe_or_contradictory_evaluation(tmp_path):
    import copy

    payload = _unavailable_source_payload(tmp_path)
    mutations = [
        {"research_only": False},
        {"can_confirm_signal": True},
        {"source_radar_admission": "ADMITTED"},
        {"source_live_trade": True},
        {"source_radar_admission": "BLOCKED"},
        {"source_live_trade": False},
        {"status": "PASS"},
        {"source_sequence": 1},
        {"source_repo_sha": "b" * 40},
        {"runtime_instance_id": "source-1"},
        {"symbols": [_state("US.QQQ", "bullish")]},
        {"reasons": []},
    ]
    for mutation in mutations:
        contradictory = copy.deepcopy(payload)
        contradictory["evaluation"].update(mutation)
        path = _write(tmp_path / "radar.json", contradictory)
        result = read_us_radar_analysis(path=path, now_utc=NOW)
        assert result["error"] == "EVALUATION_SAFETY_CONTRACT_VIOLATION", mutation
        assert result["ok"] is False
        assert result["radar_admission"] == "BLOCKED"
        assert result["live_trade"] is False

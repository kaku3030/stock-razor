from datetime import datetime, timedelta, timezone

from src.services.stock_radar_v2.cn_observation_worker import (
    CnObservationRadarWorker,
)


NOW = datetime(2026, 10, 7, 9, 40, tzinfo=timezone.utc)
SHA = "a" * 40


def _rows(frame: str):
    rows = []
    count = 140 if frame == "1d" else 160
    if frame == "1d":
        start = datetime(2026, 3, 1)
        step = timedelta(days=1)
    elif frame == "60m":
        start = datetime(2026, 9, 1, 9, 30)
        step = timedelta(hours=1)
    else:
        start = datetime(2026, 10, 1, 9, 45)
        step = timedelta(minutes=15)
    for i in range(count):
        stamp = start + step * i
        close = 1.0 + i * 0.001
        rows.append(
            {
                "label": stamp.strftime("%Y-%m-%d" if frame == "1d" else "%Y-%m-%d %H:%M"),
                "open": close - 0.001,
                "high": close + 0.002,
                "low": close - 0.002,
                "close": close,
                "volume_raw": 1000 + i,
                "volume_unit": "HAND",
                "quality_flags": [],
            }
        )
    return rows


def _payload(*, sequence=1, emitted_at=NOW - timedelta(seconds=5), repo_sha=SHA):
    frames = {}
    for frame in ("1d", "60m", "15m"):
        frames[frame] = {
            "status": "PASS",
            "rows": _rows(frame),
            "provider_used": "tencent",
            "provider_lineage": "tencent",
            "fallback_from": "eastmoney",
            "fallback_reason": "CloudObservationError",
            "timestamp_semantic": "DAILY_DATE" if frame == "1d" else "UNKNOWN",
            "currentness": "UNPROVEN",
        }
    return {
        "schema": "stock_razor_cn_eastmoney_observation_v1",
        "repo_sha": repo_sha,
        "runtime_instance_id": "cn-source-1",
        "sequence": sequence,
        "emitted_at_utc": emitted_at.isoformat(),
        "status": "PASS",
        "symbols": {
            "159611": {
                "status": "PASS",
                "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
                "providers_used": ["tencent"],
                "timeframes": frames,
                "radar_admission": "BLOCKED",
                "live_trade": False,
            }
        },
        "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
        "provider_lineages": ["eastmoney", "tencent"],
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def test_worker_evaluates_pass_source_and_keeps_analysis_research_only():
    worker = CnObservationRadarWorker(
        expected_source_repo_sha=SHA,
        now=lambda: NOW,
    )

    result = worker.evaluate_payload(_payload())

    assert result["status"] == "PASS"
    analysis = result["analysis"]
    assert analysis["status"] == "PASS"
    assert analysis["research_state_symbols"] == ["159611"]
    item = analysis["symbols"]["159611"]
    assert item["status"] == "RESEARCH_STATE"
    assert item["signal_permission"] == "record_only"
    assert item["research_only"] is True
    assert item["can_confirm_signal"] is False
    assert "cn_intraday_timestamp_semantics_unproven" in item["technical"]["risk_flags"]
    assert "cn_intraday_currentness_unproven" in item["technical"]["risk_flags"]
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_same_sequence_returns_unchanged_without_recompute_contract_drift():
    worker = CnObservationRadarWorker(
        expected_source_repo_sha=SHA,
        now=lambda: NOW,
    )
    first = worker.evaluate_payload(_payload())
    second = worker.evaluate_payload(_payload())

    assert first["status"] == "PASS"
    assert second["status"] == "UNCHANGED"
    assert second["analysis"] == first["analysis"]
    assert second["reasons"] == ["SOURCE_SEQUENCE_UNCHANGED"]


def test_source_sha_mismatch_fails_closed():
    worker = CnObservationRadarWorker(
        expected_source_repo_sha=SHA,
        now=lambda: NOW,
    )

    result = worker.evaluate_payload(_payload(repo_sha="b" * 40))

    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["SOURCE_REPO_SHA_MISMATCH"]
    assert result["analysis"] is None
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_stale_source_fails_closed():
    worker = CnObservationRadarWorker(
        expected_source_repo_sha=SHA,
        max_source_age_seconds=180,
        now=lambda: NOW,
    )

    result = worker.evaluate_payload(
        _payload(emitted_at=NOW - timedelta(minutes=10))
    )

    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["SOURCE_STALE"]


def test_sequence_regression_fails_closed():
    worker = CnObservationRadarWorker(
        expected_source_repo_sha=SHA,
        now=lambda: NOW,
    )
    assert worker.evaluate_payload(_payload(sequence=2))["status"] == "PASS"

    result = worker.evaluate_payload(_payload(sequence=1))

    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["SOURCE_SEQUENCE_REGRESSION"]

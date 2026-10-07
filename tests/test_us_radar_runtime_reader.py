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

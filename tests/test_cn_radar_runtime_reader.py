from datetime import datetime, timedelta, timezone
import json

from data_provider.cn_radar_runtime_reader import read_cn_radar_analysis


NOW = datetime(2026, 10, 7, 9, 45, tzinfo=timezone.utc)


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _symbol_state(symbol):
    return {
        "status": "RESEARCH_STATE",
        "technical": {
            "symbol": symbol,
            "risk_flags": [
                "cn_intraday_timestamp_semantics_unproven",
                "cn_intraday_currentness_unproven",
            ],
        },
        "frame_provenance": {
            "1d": {"provider_used": "tencent"},
            "60m": {"provider_used": "tencent"},
            "15m": {"provider_used": "tencent"},
        },
        "research_only": True,
        "can_confirm_signal": False,
        "signal_permission": "record_only",
    }


def _payload(*, emitted_at=NOW - timedelta(seconds=4), safe=True):
    return {
        "type": "cn_radar_research_heartbeat",
        "runtime_instance_id": "cn-radar-1",
        "worker_repo_sha": "a" * 40,
        "host_id": "host",
        "sequence": 10,
        "emitted_at_utc": emitted_at.isoformat(),
        "source_path": "/run/cn.json",
        "source_repo_sha": "b" * 40,
        "source_runtime_instance_id": "cn-source-1",
        "source_sequence": 3,
        "source_emitted_at_utc": (NOW - timedelta(seconds=8)).isoformat(),
        "source_age_seconds": 8.0,
        "poll_status": "PASS",
        "evaluation": {
            "schema": "stock_razor_cn_radar_research_v1",
            "source_repo_sha": "b" * 40,
            "source_runtime_instance_id": "cn-source-1",
            "source_sequence": 3,
            "source_emitted_at_utc": (NOW - timedelta(seconds=8)).isoformat(),
            "status": "PASS",
            "symbols": {
                "159611": _symbol_state("159611"),
                "512730": _symbol_state("512730"),
            },
            "research_state_symbols": ["159611", "512730"],
            "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
            "provider_lineages": ["eastmoney", "tencent"],
            "intraday_timestamp_semantics_proven": False,
            "intraday_currentness_proven": False,
            "research_only": True,
            "can_confirm_signal": False,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        },
        "reasons": [],
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED" if safe else "ADMITTED",
        "live_trade": False,
    }


def test_reads_precomputed_cn_analysis_and_filters_symbols(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    result = read_cn_radar_analysis(["159611"], path=path, now_utc=NOW)

    assert result["ok"] is True
    assert result["status"] == "PASS"
    assert list(result["symbols"]) == ["159611"]
    assert result["symbols"]["159611"]["signal_permission"] == "record_only"
    assert result["intraday_timestamp_semantics_proven"] is False
    assert result["intraday_currentness_proven"] is False
    assert result["read_latency_ms"] >= 0


def test_repeated_cn_analysis_read_hits_cache(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    first = read_cn_radar_analysis(path=path, now_utc=NOW)
    second = read_cn_radar_analysis(path=path, now_utc=NOW)

    assert first["source_cache_hit"] is False
    assert second["source_cache_hit"] is True
    assert set(second["symbols"]) == {"159611", "512730"}


def test_cn_analysis_stale_is_exposed_not_laundered(tmp_path):
    path = _write(
        tmp_path / "cn-radar.json",
        _payload(emitted_at=NOW - timedelta(minutes=2)),
    )

    result = read_cn_radar_analysis(path=path, now_utc=NOW, max_age_seconds=30)

    assert result["ok"] is True
    assert result["status"] == "STALE"
    assert result["source_age_seconds"] == 120


def test_cn_analysis_safety_violation_blocks(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload(safe=False))

    result = read_cn_radar_analysis(path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "INVALID"
    assert result["error"] == "SAFETY_CONTRACT_VIOLATION"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_cn_analysis_invalid_symbol_rejected(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    result = read_cn_radar_analysis(["AMD"], path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "INVALID_ARGUMENT"
    assert result["error"] == "INVALID_SYMBOL"

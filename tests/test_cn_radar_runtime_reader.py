from datetime import datetime, timedelta, timezone
import json

from data_provider.cn_radar_runtime_reader import read_cn_radar_analysis


NOW = datetime(2026, 10, 7, 10, 10, tzinfo=timezone.utc)


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _symbol_state(symbol: str):
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
            "1d": {"provider_used": "tencent", "currentness": "UNPROVEN"},
            "60m": {"provider_used": "tencent", "currentness": "UNPROVEN"},
            "15m": {"provider_used": "tencent", "currentness": "UNPROVEN"},
        },
        "providers_used": ["tencent"],
        "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
        "research_only": True,
        "can_confirm_signal": False,
        "signal_permission": "record_only",
    }


def _payload(*, emitted_at=NOW - timedelta(seconds=5), safe=True):
    return {
        "type": "cn_radar_research_heartbeat",
        "runtime_instance_id": "cn-radar-1",
        "worker_repo_sha": "a" * 40,
        "host_id": "host",
        "sequence": 9,
        "emitted_at_utc": emitted_at.isoformat(),
        "source_path": "/run/cn-observation.json",
        "source_repo_sha": "b" * 40,
        "source_runtime_instance_id": "cn-source-1",
        "source_sequence": 12,
        "source_emitted_at_utc": (NOW - timedelta(seconds=7)).isoformat(),
        "source_age_seconds": 7.0,
        "poll_status": "PASS",
        "evaluation": {
            "schema": "stock_razor_cn_radar_research_v1",
            "source_repo_sha": "b" * 40,
            "source_runtime_instance_id": "cn-source-1",
            "source_sequence": 12,
            "source_emitted_at_utc": (NOW - timedelta(seconds=7)).isoformat(),
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


def test_reads_precomputed_cn_analysis_by_symbol(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    result = read_cn_radar_analysis(["159611"], path=path, now_utc=NOW)

    assert result["ok"] is True
    assert result["status"] == "PASS"
    assert list(result["symbols"]) == ["159611"]
    assert result["symbols"]["159611"]["signal_permission"] == "record_only"
    flags = result["symbols"]["159611"]["technical"]["risk_flags"]
    assert "cn_intraday_timestamp_semantics_unproven" in flags
    assert "cn_intraday_currentness_unproven" in flags
    assert result["provider_policy"] == "EASTMONEY_PRIMARY_TENCENT_FALLBACK"
    assert result["read_latency_ms"] >= 0


def test_symbol_normalization_accepts_suffix_and_prefix(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    result = read_cn_radar_analysis(
        ["159611.SZ", "SH512730"],
        path=path,
        now_utc=NOW,
    )

    assert set(result["symbols"]) == {"159611", "512730"}
    assert result["missing_symbols"] == []


def test_no_filter_returns_all_cn_states(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    result = read_cn_radar_analysis(path=path, now_utc=NOW)

    assert set(result["symbols"]) == {"159611", "512730"}
    assert result["research_state_symbols"] == ["159611", "512730"]


def test_missing_cn_symbol_is_explicit(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    result = read_cn_radar_analysis(["159363"], path=path, now_utc=NOW)

    assert result["ok"] is True
    assert result["symbols"] == {}
    assert result["missing_symbols"] == ["159363"]


def test_stale_cn_worker_state_is_explicit(tmp_path):
    path = _write(
        tmp_path / "cn-radar.json",
        _payload(emitted_at=NOW - timedelta(minutes=2)),
    )

    result = read_cn_radar_analysis(path=path, now_utc=NOW, max_age_seconds=30)

    assert result["ok"] is True
    assert result["status"] == "STALE"
    assert result["source_age_seconds"] == 120


def test_cn_safety_contract_violation_fails_closed(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload(safe=False))

    result = read_cn_radar_analysis(path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "INVALID"
    assert result["error"] == "SAFETY_CONTRACT_VIOLATION"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_invalid_cn_symbol_rejected(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    result = read_cn_radar_analysis(["US.AMD"], path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "INVALID_ARGUMENT"
    assert result["error"] == "INVALID_SYMBOL"

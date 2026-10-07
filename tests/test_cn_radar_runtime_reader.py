from datetime import datetime, timedelta, timezone
import json

from data_provider.cn_radar_runtime_reader import read_cn_radar_analysis


NOW = datetime(2026, 10, 7, 10, 20, tzinfo=timezone.utc)


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _state(
    symbol,
    score,
    *,
    timestamp_semantics_proven=False,
    currentness_proven=False,
):
    return {
        "status": "RESEARCH_STATE",
        "technical": {
            "code": symbol,
            "research_score": score,
            "risk_flags": [
                *(
                    []
                    if timestamp_semantics_proven
                    else ["cn_intraday_timestamp_semantics_unproven"]
                ),
                *(
                    []
                    if currentness_proven
                    else ["cn_intraday_currentness_unproven"]
                ),
            ],
        },
        "frame_provenance": {
            "1d": {"provider_used": "tencent"},
            "60m": {"provider_used": "tencent"},
            "15m": {"provider_used": "tencent"},
        },
        "providers_used": ["tencent"],
        "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
        "intraday_timestamp_semantics_proven": timestamp_semantics_proven,
        "intraday_currentness_proven": currentness_proven,
        "research_only": True,
        "can_confirm_signal": False,
        "signal_permission": "record_only",
    }


def _payload(
    *,
    emitted_at=NOW - timedelta(seconds=5),
    safe=True,
    timestamp_semantics_proven=False,
    currentness_proven=False,
):
    return {
        "type": "cn_radar_research_heartbeat",
        "runtime_instance_id": "cn-radar-1",
        "worker_repo_sha": "a" * 40,
        "host_id": "host",
        "sequence": 4,
        "emitted_at_utc": emitted_at.isoformat(),
        "source_path": "/run/cn-observation.json",
        "source_repo_sha": "b" * 40,
        "source_runtime_instance_id": "cn-source-1",
        "source_sequence": 3,
        "source_emitted_at_utc": (NOW - timedelta(seconds=10)).isoformat(),
        "source_age_seconds": 10,
        "poll_status": "PASS",
        "evaluation": {
            "schema": "stock_razor_cn_radar_research_v1",
            "source_repo_sha": "b" * 40,
            "source_runtime_instance_id": "cn-source-1",
            "source_sequence": 3,
            "source_emitted_at_utc": (NOW - timedelta(seconds=10)).isoformat(),
            "status": "PASS",
            "symbols": {
                "159611": _state(
                    "159611",
                    65,
                    timestamp_semantics_proven=timestamp_semantics_proven,
                    currentness_proven=currentness_proven,
                ),
                "159363": _state(
                    "159363",
                    45,
                    timestamp_semantics_proven=timestamp_semantics_proven,
                    currentness_proven=currentness_proven,
                ),
            },
            "research_state_symbols": ["159363", "159611"],
            "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
            "provider_lineages": ["eastmoney", "tencent"],
            "intraday_timestamp_semantics_proven": timestamp_semantics_proven,
            "intraday_currentness_proven": currentness_proven,
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
    assert result["symbols"]["159611"]["technical"]["research_score"] == 65
    assert result["provider_policy"] == "EASTMONEY_PRIMARY_TENCENT_FALLBACK"
    assert result["read_latency_ms"] >= 0
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_qualified_bar_end_semantics_are_preserved_in_fast_analysis(tmp_path):
    path = _write(
        tmp_path / "cn-radar.json",
        _payload(timestamp_semantics_proven=True),
    )

    result = read_cn_radar_analysis(["159611"], path=path, now_utc=NOW)

    assert result["ok"] is True
    assert result["intraday_timestamp_semantics_proven"] is True
    assert result["intraday_currentness_proven"] is False
    state = result["symbols"]["159611"]
    assert state["intraday_timestamp_semantics_proven"] is True
    assert state["intraday_currentness_proven"] is False
    assert "cn_intraday_timestamp_semantics_unproven" not in (
        state["technical"]["risk_flags"]
    )
    assert "cn_intraday_currentness_unproven" in state["technical"]["risk_flags"]
    assert state["signal_permission"] == "record_only"


def test_proven_currentness_is_preserved_without_admission(tmp_path):
    path = _write(
        tmp_path / "cn-radar.json",
        _payload(
            timestamp_semantics_proven=True,
            currentness_proven=True,
        ),
    )

    result = read_cn_radar_analysis(["159611"], path=path, now_utc=NOW)

    assert result["ok"] is True
    assert result["intraday_currentness_proven"] is True
    state = result["symbols"]["159611"]
    assert state["intraday_currentness_proven"] is True
    assert "cn_intraday_currentness_unproven" not in state["technical"]["risk_flags"]
    assert state["signal_permission"] == "record_only"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_no_filter_returns_all_research_states(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    result = read_cn_radar_analysis(path=path, now_utc=NOW)

    assert set(result["symbols"]) == {"159611", "159363"}
    assert result["missing_symbols"] == []


def test_missing_symbol_is_explicit(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    result = read_cn_radar_analysis(["512730"], path=path, now_utc=NOW)

    assert result["ok"] is True
    assert result["symbols"] == {}
    assert result["missing_symbols"] == ["512730"]


def test_stale_cn_analysis_is_marked_stale(tmp_path):
    path = _write(
        tmp_path / "cn-radar.json",
        _payload(emitted_at=NOW - timedelta(minutes=5)),
    )

    result = read_cn_radar_analysis(
        path=path,
        now_utc=NOW,
        max_age_seconds=180,
    )

    assert result["ok"] is True
    assert result["status"] == "STALE"
    assert result["source_age_seconds"] == 300


def test_top_level_safety_drift_blocks(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload(safe=False))

    result = read_cn_radar_analysis(path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "INVALID"
    assert result["error"] == "SAFETY_CONTRACT_VIOLATION"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_invalid_symbol_fails_closed(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    result = read_cn_radar_analysis(["US.AMD"], path=path, now_utc=NOW)

    assert result["ok"] is False
    assert result["status"] == "INVALID_ARGUMENT"
    assert result["error"] == "INVALID_SYMBOL"


def test_second_read_hits_inode_mtime_cache(tmp_path):
    path = _write(tmp_path / "cn-radar.json", _payload())

    first = read_cn_radar_analysis(["159611"], path=path, now_utc=NOW)
    second = read_cn_radar_analysis(["159611"], path=path, now_utc=NOW)

    assert first["source_cache_hit"] is False
    assert second["source_cache_hit"] is True

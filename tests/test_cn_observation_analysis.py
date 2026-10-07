from datetime import datetime, timedelta, timezone

import pytest

from src.services.stock_radar_v2.cn_observation_analysis import (
    CN_RADAR_SCHEMA,
    CnObservationAnalysisError,
    evaluate_cn_observation_payload,
)


NOW = datetime(2026, 10, 7, 8, 10, tzinfo=timezone.utc)


def _daily_rows(count=80):
    start = datetime(2026, 6, 1)
    rows = []
    for i in range(count):
        day = start + timedelta(days=i)
        close = 1.5 + i * 0.002
        rows.append({
            "label": day.strftime("%Y-%m-%d"),
            "provider_label_raw": day.strftime("%Y%m%d"),
            "open": close - 0.01,
            "high": close + 0.02,
            "low": close - 0.02,
            "close": close,
            "volume_raw": 1000 + i,
            "volume_unit": "HAND",
            "amount_raw": None,
            "amount_unit": "UNAVAILABLE",
            "provider": "tencent",
            "quality_flags": [],
        })
    return rows


def _minute_rows(minutes, count=100):
    start = datetime(2026, 9, 25, 9, 30)
    rows = []
    for i in range(count):
        stamp = start + timedelta(minutes=minutes * i)
        close = 1.6 + i * 0.001
        rows.append({
            "label": stamp.strftime("%Y-%m-%d %H:%M"),
            "provider_label_raw": stamp.strftime("%Y%m%d%H%M"),
            "open": close - 0.005,
            "high": close + 0.01,
            "low": close - 0.01,
            "close": close,
            "volume_raw": 1500 + i,
            "volume_unit": "HAND",
            "amount_raw": None,
            "amount_unit": "UNAVAILABLE",
            "provider": "tencent",
            "quality_flags": [],
        })
    return rows


def _frame(rows, timeframe):
    return {
        "status": "PASS",
        "error": None,
        "row_count": len(rows),
        "rows": rows,
        "request_latency_ms": 50.0,
        "provider_used": "tencent",
        "provider_lineage": "tencent",
        "fallback_from": "eastmoney",
        "fallback_reason": "CloudObservationError",
        "timestamp_semantic": "DAILY_DATE" if timeframe == "1d" else "UNKNOWN",
        "currentness": "UNPROVEN",
        "adjustment": "NONE",
    }


def _payload(*, safe=True, symbol_status="PASS"):
    return {
        "schema": "stock_razor_cn_eastmoney_observation_v1",
        "repo_sha": "a" * 40,
        "runtime_instance_id": "cn-runtime-1",
        "sequence": 7,
        "emitted_at_utc": NOW.isoformat(),
        "status": "PASS",
        "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
        "providers_used": ["tencent"],
        "provider_lineages": ["eastmoney", "tencent"],
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED" if safe else "ADMITTED",
        "live_trade": False,
        "symbols": {
            "159611": {
                "symbol": "159611",
                "status": symbol_status,
                "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
                "providers_used": ["tencent"],
                "radar_admission": "BLOCKED",
                "live_trade": False,
                "timeframes": {
                    "1d": _frame(_daily_rows(), "1d"),
                    "60m": _frame(_minute_rows(60), "60m"),
                    "15m": _frame(_minute_rows(15), "15m"),
                },
            }
        },
    }


def test_cn_observation_builds_research_state_with_three_timeframes():
    result = evaluate_cn_observation_payload(_payload())

    assert result["schema"] == CN_RADAR_SCHEMA
    assert result["status"] == "PASS"
    assert result["research_state_symbols"] == ["159611"]
    state = result["symbols"]["159611"]
    assert state["status"] == "RESEARCH_STATE"
    assert state["technical"]["daily"]["quality"]["status"] != "missing"
    assert state["technical"]["hourly"]["quality"]["status"] == "partial"
    assert state["technical"]["intraday"]["quality"]["status"] == "partial"
    assert state["technical"]["hourly"]["confidence"] <= 0.65
    assert state["technical"]["intraday"]["confidence"] <= 0.65
    assert "cn_intraday_timestamp_semantics_unproven" in state["technical"]["risk_flags"]
    assert "cn_intraday_currentness_unproven" in state["technical"]["risk_flags"]


def test_cn_analysis_preserves_provider_and_fallback_provenance():
    result = evaluate_cn_observation_payload(_payload())
    provenance = result["symbols"]["159611"]["frame_provenance"]

    assert provenance["1d"]["provider_used"] == "tencent"
    assert provenance["60m"]["provider_lineage"] == "tencent"
    assert provenance["15m"]["fallback_from"] == "eastmoney"
    assert provenance["15m"]["fallback_reason"] == "CloudObservationError"
    assert provenance["15m"]["timestamp_semantic"] == "UNKNOWN"
    assert provenance["15m"]["currentness"] == "UNPROVEN"


def test_symbol_source_not_pass_is_blocked_without_analysis():
    result = evaluate_cn_observation_payload(_payload(symbol_status="PARTIAL"))

    assert result["status"] == "BLOCKED"
    item = result["symbols"]["159611"]
    assert item["status"] == "BLOCKED"
    assert item["reasons"] == ["SYMBOL_SOURCE_NOT_PASS"]


def test_structural_invalidity_blocks_symbol_fail_closed():
    payload = _payload()
    payload["symbols"]["159611"]["timeframes"]["15m"]["rows"][-1]["quality_flags"] = [
        "INVALID_OHLC"
    ]

    result = evaluate_cn_observation_payload(payload)

    assert result["status"] == "BLOCKED"
    assert result["symbols"]["159611"]["status"] == "BLOCKED"
    assert result["symbols"]["159611"]["reasons"] == [
        "ANALYSIS_ERROR:CnObservationAnalysisError"
    ]


def test_root_safety_contract_violation_raises():
    with pytest.raises(CnObservationAnalysisError):
        evaluate_cn_observation_payload(_payload(safe=False))


def test_output_never_promotes_currentness_or_trading():
    result = evaluate_cn_observation_payload(_payload())

    assert result["intraday_timestamp_semantics_proven"] is False
    assert result["intraday_currentness_proven"] is False
    assert result["research_only"] is True
    assert result["can_confirm_signal"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert result["symbols"]["159611"]["signal_permission"] == "record_only"

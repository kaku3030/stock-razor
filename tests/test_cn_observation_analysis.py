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


def _frame(rows, timeframe, *, qualified=False, currentness_proven=False):
    timestamp_semantic = "DAILY_DATE" if timeframe == "1d" else (
        "BAR_END" if qualified else "UNKNOWN"
    )
    timestamp_qualification = None
    currentness_qualification = None
    if qualified and timeframe in {"15m", "60m"}:
        timestamp_qualification = {
            "status": "PASS",
            "timestamp_semantic": "BAR_END",
            "currentness_proven": False,
            "continuity_proven": False,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }
        currentness_qualification = {
            "status": "PASS" if currentness_proven else "BLOCKED",
            "timestamp_semantic": "BAR_END",
            "currentness_proven": currentness_proven,
            "continuity_proven": False,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }
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
        "timestamp_semantic": timestamp_semantic,
        "timestamp_qualification": timestamp_qualification,
        "currentness_qualification": currentness_qualification,
        "currentness": "PROVEN" if currentness_proven else "UNPROVEN",
        "adjustment": "NONE",
    }


def _payload(
    *,
    safe=True,
    symbol_status="PASS",
    timestamp_semantics_proven=False,
    currentness_proven=False,
):
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
        "intraday_timestamp_semantics_proven": timestamp_semantics_proven,
        "intraday_currentness_proven": currentness_proven,
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
                "intraday_timestamp_semantics_proven": timestamp_semantics_proven,
                "intraday_currentness_proven": currentness_proven,
                "timeframes": {
                    "1d": _frame(_daily_rows(), "1d"),
                    "60m": _frame(
                        _minute_rows(60),
                        "60m",
                        qualified=timestamp_semantics_proven,
                        currentness_proven=currentness_proven,
                    ),
                    "15m": _frame(
                        _minute_rows(15),
                        "15m",
                        qualified=timestamp_semantics_proven,
                        currentness_proven=currentness_proven,
                    ),
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


def test_qualified_bar_end_removes_only_timestamp_semantics_risk():
    result = evaluate_cn_observation_payload(
        _payload(timestamp_semantics_proven=True)
    )

    assert result["status"] == "PASS"
    assert result["intraday_timestamp_semantics_proven"] is True
    assert result["intraday_currentness_proven"] is False
    state = result["symbols"]["159611"]
    assert state["intraday_timestamp_semantics_proven"] is True
    assert state["intraday_currentness_proven"] is False
    assert state["signal_permission"] == "record_only"
    assert "cn_intraday_timestamp_semantics_unproven" not in state["technical"]["risk_flags"]
    assert "cn_intraday_currentness_unproven" in state["technical"]["risk_flags"]
    assert state["technical"]["hourly"]["quality"]["status"] == "partial"
    assert state["technical"]["intraday"]["quality"]["status"] == "partial"
    assert state["technical"]["hourly"]["confidence"] <= 0.65
    assert state["technical"]["intraday"]["confidence"] <= 0.65
    assert "1h_timestamp_semantics_unproven" not in (
        state["technical"]["hourly"]["quality"]["warnings"]
    )
    assert "1h_currentness_unproven" in (
        state["technical"]["hourly"]["quality"]["warnings"]
    )
    assert "15m_timestamp_semantics_unproven" not in (
        state["technical"]["intraday"]["quality"]["warnings"]
    )
    assert "15m_currentness_unproven" in (
        state["technical"]["intraday"]["quality"]["warnings"]
    )


def test_proven_currentness_removes_currentness_risk_without_admission():
    result = evaluate_cn_observation_payload(
        _payload(
            timestamp_semantics_proven=True,
            currentness_proven=True,
        )
    )

    assert result["status"] == "PASS"
    assert result["intraday_timestamp_semantics_proven"] is True
    assert result["intraday_currentness_proven"] is True
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    state = result["symbols"]["159611"]
    assert state["intraday_currentness_proven"] is True
    assert state["signal_permission"] == "record_only"
    assert "cn_intraday_currentness_unproven" not in state["technical"]["risk_flags"]
    assert "1h_currentness_unproven" not in (
        state["technical"]["hourly"]["quality"]["warnings"]
    )
    assert "15m_currentness_unproven" not in (
        state["technical"]["intraday"]["quality"]["warnings"]
    )


def test_forged_root_bar_end_claim_cannot_launder_unqualified_frames():
    payload = _payload()
    payload["intraday_timestamp_semantics_proven"] = True

    result = evaluate_cn_observation_payload(payload)

    assert result["status"] == "BLOCKED"
    assert result["intraday_timestamp_semantics_proven"] is False
    assert result["symbols"]["159611"]["status"] == "BLOCKED"
    assert result["symbols"]["159611"]["reasons"] == [
        "ANALYSIS_ERROR:CnObservationAnalysisError"
    ]


def test_bar_end_claim_with_failed_qualification_blocks_symbol():
    payload = _payload(timestamp_semantics_proven=True)
    payload["symbols"]["159611"]["timeframes"]["15m"][
        "timestamp_qualification"
    ]["status"] = "BLOCKED"

    result = evaluate_cn_observation_payload(payload)

    assert result["status"] == "BLOCKED"
    assert result["symbols"]["159611"]["status"] == "BLOCKED"


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


def test_tencent_opening_auction_range_gap_is_soft_research_risk():
    payload = _payload()
    frames = payload["symbols"]["159611"]["timeframes"]

    first_15m = next(
        row for row in frames["15m"]["rows"] if row["label"].endswith("09:45")
    )
    first_15m["open"] = first_15m["low"] - 0.003
    first_15m["quality_flags"] = ["INVALID_OHLC"]

    first_60m = next(
        row for row in frames["60m"]["rows"] if row["label"].endswith("10:30")
    )
    first_60m["open"] = first_60m["low"] - 0.003
    first_60m["quality_flags"] = ["INVALID_OHLC"]

    result = evaluate_cn_observation_payload(payload)

    assert result["status"] == "PASS"
    state = result["symbols"]["159611"]
    assert state["status"] == "RESEARCH_STATE"
    assert "cn_opening_auction_range_gap" in state["technical"]["risk_flags"]
    assert "OPENING_AUCTION_RANGE_GAP" in (
        state["frame_provenance"]["15m"]["analysis_warnings"]
    )
    assert "OPENING_AUCTION_RANGE_GAP" in (
        state["frame_provenance"]["60m"]["analysis_warnings"]
    )


def test_non_opening_invalid_ohlc_remains_hard_block():
    payload = _payload()
    row = payload["symbols"]["159611"]["timeframes"]["15m"]["rows"][-1]
    row["open"] = row["low"] - 0.003
    row["quality_flags"] = ["INVALID_OHLC"]

    result = evaluate_cn_observation_payload(payload)

    assert result["status"] == "BLOCKED"
    assert result["symbols"]["159611"]["status"] == "BLOCKED"


def test_opening_bar_with_close_outside_range_remains_hard_block():
    payload = _payload()
    row = next(
        item
        for item in payload["symbols"]["159611"]["timeframes"]["15m"]["rows"]
        if item["label"].endswith("09:45")
    )
    row["open"] = row["low"] - 0.003
    row["close"] = row["high"] + 0.01
    row["quality_flags"] = ["INVALID_OHLC"]

    result = evaluate_cn_observation_payload(payload)

    assert result["status"] == "BLOCKED"
    assert result["symbols"]["159611"]["status"] == "BLOCKED"


def test_real_512730_tencent_opening_rows_are_soft_only_at_session_open():
    payload = _payload()
    symbol = payload["symbols"].pop("159611")
    payload["symbols"]["512730"] = symbol

    frames = symbol["timeframes"]
    exact_cases = {
        "15m": ("2026-08-19 09:45", 1.645, 1.656, 1.659, 1.648),
        "60m": ("2026-08-19 10:30", 1.645, 1.659, 1.660, 1.648),
    }
    for timeframe, (label, open_, close, high, low) in exact_cases.items():
        row = frames[timeframe]["rows"][0]
        row.update({
            "label": label,
            "provider_label_raw": label.replace("-", "").replace(" ", "").replace(":", ""),
            "open": open_,
            "close": close,
            "high": high,
            "low": low,
            "quality_flags": ["INVALID_OHLC"],
            "provider": "tencent",
        })
        # Keep remaining rows strictly after the real opening label.
        base = datetime.fromisoformat(label)
        step = 15 if timeframe == "15m" else 60
        for index, later in enumerate(frames[timeframe]["rows"][1:], start=1):
            stamp = base + timedelta(minutes=step * index)
            later["label"] = stamp.strftime("%Y-%m-%d %H:%M")
            later["provider_label_raw"] = stamp.strftime("%Y%m%d%H%M")

    result = evaluate_cn_observation_payload(payload)

    assert result["status"] == "PASS"
    state = result["symbols"]["512730"]
    assert state["status"] == "RESEARCH_STATE"
    assert "cn_opening_auction_range_gap" in state["technical"]["risk_flags"]

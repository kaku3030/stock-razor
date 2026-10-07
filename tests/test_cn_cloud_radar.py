from datetime import datetime, timedelta, timezone

from src.services.stock_radar_v2.cn_cloud_radar import CNCloudRadarEvaluator

NOW = datetime(2026, 10, 7, 8, 30, tzinfo=timezone.utc)
SHA = "a" * 40


def rows(count, frame, provider="tencent"):
    out = []
    start = datetime(2026, 1, 1, 9, 30)
    for i in range(count):
        label = (
            (start + timedelta(days=i)).strftime("%Y-%m-%d")
            if frame == "1d"
            else (start + timedelta(minutes=i * (60 if frame == "60m" else 15))).strftime("%Y-%m-%d %H:%M")
        )
        p = 1 + i * 0.01
        out.append({
            "label": label,
            "open": p,
            "high": p + 0.02,
            "low": p - 0.01,
            "close": p + 0.01,
            "volume_raw": 1000 + i,
            "quality_flags": [],
        })
    return out


def frame(name, count, provider="tencent"):
    return {
        "status": "PASS",
        "rows": rows(count, name, provider),
        "provider_used": provider,
        "provider_lineage": provider,
        "fallback_from": "eastmoney" if provider == "tencent" else None,
        "timestamp_semantic": "DAILY_DATE" if name == "1d" else "UNKNOWN",
        "currentness": "UNPROVEN",
    }


def payload(emitted=None):
    return {
        "schema": "stock_razor_cn_eastmoney_observation_v1",
        "repo_sha": SHA,
        "runtime_instance_id": "cn-1",
        "sequence": 4,
        "emitted_at_utc": (emitted or NOW - timedelta(seconds=30)).isoformat(),
        "status": "PASS",
        "symbols": {
            "159611": {
                "status": "PASS",
                "timeframes": {
                    "1d": frame("1d", 260),
                    "60m": frame("60m", 240),
                    "15m": frame("15m", 480),
                },
                "intraday_timestamp_semantics_proven": False,
                "intraday_currentness_proven": False,
                "research_only": True,
                "can_confirm_signal": False,
                "radar_admission": "BLOCKED",
                "live_trade": False,
            }
        },
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def test_full_three_timeframe_state_remains_research_only():
    result = CNCloudRadarEvaluator().evaluate_payload(payload(), expected_repo_sha=SHA, now_utc=NOW)
    assert result.status == "PASS"
    item = result.symbols[0]
    tech = item["technical"]
    assert item["status"] == "RESEARCH_STATE"
    assert tech["daily"]["quality"]["bars"] == 260
    assert tech["hourly"]["quality"]["bars"] == 240
    assert tech["intraday"]["quality"]["bars"] == 480
    assert tech["hourly"]["confidence"] <= 0.65
    assert tech["intraday"]["confidence"] <= 0.65
    assert "1h_timestamp_semantics_unverified" in tech["hourly"]["quality"]["warnings"]
    assert "15m_currentness_unproven" in tech["intraday"]["quality"]["warnings"]
    assert "provider_fallback_used" in tech["risk_flags"]
    assert item["can_confirm_signal"] is False
    assert item["radar_admission"] == "BLOCKED"
    assert item["live_trade"] is False


def test_stale_source_blocks():
    result = CNCloudRadarEvaluator(max_age_seconds=180).evaluate_payload(
        payload(NOW - timedelta(seconds=181)),
        expected_repo_sha=SHA,
        now_utc=NOW,
    )
    assert result.status == "BLOCKED"
    assert result.reasons == ("SOURCE_STALE",)
    assert result.symbols == ()


def test_structural_quality_flag_blocks_symbol():
    body = payload()
    body["symbols"]["159611"]["timeframes"]["15m"]["rows"][-1]["quality_flags"] = ["INVALID_OHLC"]
    result = CNCloudRadarEvaluator().evaluate_payload(body, expected_repo_sha=SHA, now_utc=NOW)
    assert result.status == "PARTIAL"
    assert result.symbols[0]["status"] == "BLOCKED"
    assert result.symbols[0]["reasons"] == ["15m:STRUCTURAL_QUALITY_FLAG_PRESENT"]

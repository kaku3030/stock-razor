"""Fail-closed tests for the scheduled OpenD cloud 15m research digest."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import importlib.util

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/us_opend_15m_digest.py"
_spec = importlib.util.spec_from_file_location("us_opend_15m_digest", _SCRIPT)
reporter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reporter)

NOW = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def sample():
    stamp = (NOW - timedelta(minutes=1)).isoformat()
    bar = {
        "bar_end_utc": stamp, "open": 100.0, "high": 105.0, "low": 95.0,
        "close": 101.0, "volume": 200, "feed": "opend", "provider": "futu",
        "quality_flags": [], "is_closed": True, "is_complete": True
    }
    hb = {"repo_sha": SHA, "runtime_instance_id": "livefeed", "bar_closure": "PROVEN"}
    # Keep each timeframe independent so a test mutation to one bar cannot leak into another.
    import copy
    market = {
        "repo_sha": SHA, "runtime_instance_id": "livefeed",
        "radar_admission": "BLOCKED", "live_trade": False,
        "sequence": 3, "bar_closure": "PROVEN",
        "latest_source_timestamp_utc": stamp,
        "symbols": {
            "US.QQQ": {"feed": "opend", "provider": "futu",
                       "timeframes": {
                           "1m": [copy.deepcopy(bar)], "5m": [copy.deepcopy(bar)],
                           "15m": [copy.deepcopy(bar)], "1h": [copy.deepcopy(bar)],
                       }}
        },
    }
    # A qualified digest requires all watched symbols to have safe 15m and 1h frames.
    for name in reporter.SYMBOLS:
        market["symbols"][name] = copy.deepcopy(market["symbols"]["US.QQQ"])
    radar = {
        "worker_repo_sha": SHA, "expected_source_repo_sha": SHA,
        "poll_status": "PASS", "radar_analysis_performed": True,
        "live_trade": False,
        "evaluation": {
            "source_sequence": 3,
            "symbols": [
                {"symbol": "US.QQQ", "status": "RESEARCH_STATE",
                 "technical_state": {
                     "alignment": "aligned_bearish",
                     "watch_conditions": ["观察支撑 95 是否保持"],
                     "technical": {
                         "daily": {"trend": "bearish", "quality": {
                             "as_of": (NOW - timedelta(days=1)).isoformat()}},
                         "hourly": {"trend": "bearish"},
                         "intraday": {"trend": "neutral"},
                     }
                 }}
            ],
        },
    }
    return hb, market, radar


def test_fresh_all_periods_are_only_research():
    report = reporter.render(*sample(), NOW)
    assert report["schema"] == "stock_razor_us_opend_15m_digest_v1"
    assert report["status"] == "RESEARCH_ONLY"
    assert report["can_confirm_signal"] is False
    assert report["monitor_status"] == "ACTIVE"
    assert report["can_confirm_research_alignment"] is True
    assert report["symbol_monitor"]["US.QQQ"]["research_confirmation"] == "CONFIRMED_MTF_RESEARCH"
    assert report["radar_admission"] == "BLOCKED"
    assert report["live_trade"] is False
    assert "QQQ D1:bearish 1H:bearish 15m:neutral" in report["message"]


def test_stale_cache_blocks():
    hb, market, radar = sample()
    market["latest_source_timestamp_utc"] = (NOW - timedelta(hours=5)).isoformat()
    result = reporter.render(hb, market, radar, NOW)
    assert result["status"] == "BLOCKED"
    assert "FRESHNESS" in result["message"]


def test_source_lineage_mismatch_blocks():
    hb, market, radar = sample()
    market["repo_sha"] = "b" * 40
    result = reporter.render(hb, market, radar, NOW)
    assert result["status"] == "BLOCKED"
    assert "SOURCE_LINEAGE" in result["message"]


def test_provisional_bar_cannot_be_used_as_15m_trigger():
    hb, market, radar = sample()
    market["symbols"]["US.QQQ"]["timeframes"]["15m"][0]["is_closed"] = False
    result = reporter.render(hb, market, radar, NOW)
    assert "15m:UNKNOWN" in result["message"]
    assert "bad_or_stale" in result["message"]


def test_nonfinite_bar_cannot_be_used_as_trigger():
    hb, market, radar = sample()
    market["symbols"]["US.QQQ"]["timeframes"]["15m"][0]["close"] = float("nan")
    result = reporter.render(hb, market, radar, NOW)
    assert "15m:UNKNOWN" in result["message"]


def test_missing_cache_fails_closed_without_order():
    report = reporter.render({}, {}, {}, NOW)
    assert report["status"] == "BLOCKED"
    assert report["live_trade"] is False
    assert "FRESHNESS" in report["message"]
    assert len(report["message"]) <= 1900


def test_non_opend_symbol_never_gets_fallback():
    hb, market, radar = sample()
    market["symbols"]["US.QQQ"]["provider"] = "yahoo"
    report = reporter.render(hb, market, radar, NOW)
    assert "QQQ OpenD缺失" in report["message"]

def test_forming_intraday_bars_remain_watchable_but_not_confirmed():
    hb, market, radar = sample()
    market["symbols"]["US.QQQ"]["timeframes"]["15m"][0]["is_closed"] = False
    report = reporter.render(hb, market, radar, NOW)
    assert report["symbol_monitor"]["US.QQQ"]["watch_status"] == "ACTIVE"
    assert report["symbol_monitor"]["US.QQQ"]["1m_state"] == "WATCH"
    assert report["symbol_monitor"]["US.QQQ"]["research_confirmation"] == "PROVISIONAL_OR_WAITING"
    assert report["can_confirm_signal"] is False


def test_stale_1m_blocks_live_watch_without_erasing_other_symbols():
    hb, market, radar = sample()
    old = (NOW - timedelta(minutes=8)).isoformat()
    market["symbols"]["US.QQQ"]["timeframes"]["1m"][0]["bar_end_utc"] = old
    report = reporter.render(hb, market, radar, NOW)
    assert report["symbol_monitor"]["US.QQQ"]["watch_status"] == "BLOCKED"
    assert report["symbol_monitor"]["US.AMD"]["watch_status"] == "ACTIVE"
    assert report["can_confirm_signal"] is False

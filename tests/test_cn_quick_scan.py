"""Fast CN MCP read seam: safe, tiny, single-call research preview."""
from datetime import datetime, timezone

import pytest

from data_provider import cn_fast_research_brief as module

NOW = datetime(2026, 10, 13, 4, 0, tzinfo=timezone.utc)


def _radar():
    return {
        "ok": True, "status": "PASS", "poll_status": "PASS",
        "source_repo_sha": "a" * 40,
        "source_runtime_instance_id": "source-1", "source_sequence": 7,
        "source_emitted_at_utc": NOW.isoformat(),
        "source_age_seconds_reported": 1,
        "emitted_at_utc": NOW.isoformat(), "source_age_seconds": 1,
        "radar_analysis_latency_ms": 45.0,
        "data_to_radar_latency_ms": 70.0,
        "radar_admission": "BLOCKED", "research_only": True,
        "live_trade": False, "can_confirm_signal": False,
        "symbols": {
            "159611": {
                "status": "RESEARCH_STATE", "intraday_currentness_proven": False,
                "signal_permission": "record_only",
                "research_only": True, "can_confirm_signal": False,
                "technical": {
                    "research_score": 62,
                    "risk_flags": ["cn_intraday_currentness_unproven"],
                    "watch_conditions": ["await close"],
                    "alignment": "WATCH",
                },
                "frame_provenance": {},
            }
        },
    }


def _market(symbol, timeframe="1d", limit=1, **kwargs):
    assert symbol == "159611"
    assert limit == 1
    return {
        "ok": True, "status": "PASS", "research_only": True,
        "live_trade": False, "radar_admission": "BLOCKED",
        "repo_sha": "a" * 40, "runtime_instance_id": "source-1",
        "sequence": 7, "emitted_at_utc": NOW.isoformat(),
        "source_age_seconds": 1,
        "symbol": symbol, "timeframe": timeframe,
        "provider_used": "eastmoney", "fallback_from": None,
        "timestamp_semantic": "UNKNOWN", "currentness": "UNPROVEN",
        "symbol_intraday_currentness_proven": False,
        "rows": [{"label": "2026-10-13 11:45", "close": 1.1}],
        "read_latency_ms": 1.5,
    }


def test_fast_preview_is_small_fail_closed_and_separates_timing(monkeypatch):
    called = []
    monkeypatch.setattr(module, "read_cn_radar_analysis", lambda *a, **kw: _radar())
    def market(*args, **kwargs):
        called.append(kwargs["timeframe"])
        return _market(*args, **kwargs)
    monkeypatch.setattr(module, "read_cn_market_data", market)
    brief = module.read_cn_quick_scan(["159611.SZ"], now_utc=NOW)
    assert brief["status"] == "RESEARCH_ONLY"
    assert brief["entry_gate"] == "ENTRY_BLOCKED"
    assert brief["radar_admission"] == "BLOCKED"
    assert brief["trading_authority"] is False
    assert brief["provider_requests"] == 0
    assert called == ["1d", "60m", "15m"]
    assert brief["performance"]["radar_analysis_ms"] == 45.0
    assert brief["performance"]["reader_total_ms"] >= 0
    assert brief["performance"]["chatgpt_analysis_ms"] is None
    assert brief["performance"]["user_visible_total_ms"] is None
    symbol = brief["symbols"]["159611"]
    assert symbol["frames"]["15m"]["bar_status"] == "UNKNOWN"
    assert symbol["frames"]["1d"]["bar_status"] == "UNKNOWN"
    assert symbol["frames"]["15m"]["provider"] == "eastmoney"
    assert "rows" not in str(brief)


@pytest.mark.parametrize("symbols", ["159611", ["INVALID"], [True], ["159611"] * 9])
def test_invalid_input_never_reads(monkeypatch, symbols):
    monkeypatch.setattr(module, "read_cn_radar_analysis", lambda *a, **kw: pytest.fail("read"))
    result = module.read_cn_quick_scan(symbols, now_utc=NOW)
    assert result["entry_gate"] == "ENTRY_BLOCKED"
    assert result["status"] == "INVALID_ARGUMENT"


@pytest.mark.parametrize("mutation,expected", [
    ({"status": "STALE"}, "RADAR_NOT_FRESH"),
    ({"radar_admission": "ADMITTED"}, "RADAR_NOT_QUALIFIED"),
])
def test_radar_guard_fails_before_market_read(monkeypatch, mutation, expected):
    monkeypatch.setattr(module, "read_cn_radar_analysis", lambda *a, **kw: {**_radar(), **mutation})
    monkeypatch.setattr(module, "read_cn_market_data", lambda *a, **kw: pytest.fail("market read"))
    result = module.read_cn_quick_scan(["159611"], now_utc=NOW)
    assert expected in result["reasons"]
    assert result["symbols"] == {}
    assert result["entry_gate"] == "ENTRY_BLOCKED"


def test_source_mismatch_rejects_all_symbols(monkeypatch):
    monkeypatch.setattr(module, "read_cn_radar_analysis", lambda *a, **kw: _radar())
    monkeypatch.setattr(module, "read_cn_market_data", lambda *a, **kw: {**_market(*a, **kw), "sequence": 99})
    result = module.read_cn_quick_scan(["159611"], now_utc=NOW)
    assert result["status"] == "BLOCKED"
    assert result["symbols"] == {}
    assert "SOURCE_IDENTITY_MISMATCH" in result["reasons"]


def test_reader_error_fails_closed(monkeypatch):
    monkeypatch.setattr(module, "read_cn_radar_analysis", lambda *a, **kw: _radar())
    def broken(*args, **kwargs):
        raise OSError("private path")
    monkeypatch.setattr(module, "read_cn_market_data", broken)
    result = module.read_cn_quick_scan(["159611"], now_utc=NOW)
    assert result["reasons"] == ["SOURCE_READER_ERROR"]
    assert result["symbols"] == {}
    assert "private path" not in str(result)

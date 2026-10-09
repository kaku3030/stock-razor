from datetime import datetime, timedelta, timezone

from data_provider import us_fast_research_brief as module

NOW = datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc)


def _market():
    return {
        "ok": True, "status": "PASS", "repo_sha": "b" * 40,
        "runtime_instance_id": "source-r1", "sequence": 3,
        "emitted_at_utc": NOW.isoformat(), "source_age_seconds": 1,
        "delivery_mode": "REALTIME", "bar_closure": "UNPROVEN",
        "symbols": {"US.AMD": {
            "provider": "futu", "feed": "opend",
            "health": {"grade": "good", "signal_permission": "normal"},
            "counts": {"1m": 100, "5m": 30, "15m": 10, "1h": 3},
            "latest": {"1m": {
                "close": 163, "volume": 200, "bar_end_utc": NOW.isoformat(),
                "is_closed": True, "is_complete": True, "quality_flags": [],
            }, "5m": None, "15m": None, "1h": None},
        }},
    }


def _radar():
    return {
        "ok": True, "status": "PASS",
        "worker_repo_sha": "a" * 40, "expected_source_repo_sha": "b" * 40,
        "source_runtime_instance_id": "source-r1", "source_sequence": 3,
        "emitted_at_utc": NOW.isoformat(), "source_age_seconds": 0.5,
        "poll_status": "UNCHANGED",
        "source_delivery_mode": "REALTIME", "source_bar_closure": "UNPROVEN",
        "radar_analysis_latency_ms": None, "data_to_radar_latency_ms": None,
        "symbols": {"US.AMD": {
            "status": "RESEARCH_STATE", "reasons": ["PROMOTION_NOT_AUTHORIZED"],
            "technical_state": {
                "as_of": NOW.isoformat(), "quality_flags": [],
                "technical": {
                    "alignment": "bullish", "research_score": 65,
                    "state_summary": "bullish observation only",
                    "risk_flags": ["unproven_closure"],
                    "watch_conditions": ["confirm close"],
                    "structure": {"support_levels": [159], "resistance_levels": [170]},
                    "daily": {"trend": "up", "confidence": 0.7, "quality": {"status": "partial"}},
                    "hourly": {"trend": "up"},
                    "intraday": {"trend": "down"},
                },
            },
        }},
    }


def _patch(monkeypatch, market=None, radar=None):
    counters = {"market": 0, "radar": 0}
    def read_market(*args, **kwargs):
        counters["market"] += 1
        return _market() if market is None else market
    def read_radar(*args, **kwargs):
        counters["radar"] += 1
        return _radar() if radar is None else radar
    monkeypatch.setattr(module, "read_us_market_snapshots", read_market)
    monkeypatch.setattr(module, "read_us_radar_analysis", read_radar)
    return counters


def test_one_call_combines_exactly_two_precomputed_sources_without_hallucinated_trade(monkeypatch):
    counts = _patch(monkeypatch)
    result = module.read_us_fast_research_brief(["AMD", "amd"], now_utc=NOW)
    assert counts == {"market": 1, "radar": 1}
    assert result["ok"] is True
    assert result["status"] == "ALIGNED_RESEARCH_ONLY"
    assert result["provider_requests"] == 0
    assert result["model_inference_performed"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert result["can_confirm_signal"] is False
    assert result["symbols"]["US.AMD"]["latest_bars"]["1m"]["close"] == 163
    assert result["symbols"]["US.AMD"]["multitimeframe"]["daily"]["trend"] == "up"
    assert result["symbols"]["US.AMD"]["multitimeframe"]["intraday_15m"]["trend"] == "down"
    assert result["symbols"]["US.AMD"]["signal_permission"] == "BLOCKED"
    assert result["provenance"]["market_sequence"] == result["provenance"]["radar_source_sequence"] == 3
    assert result["read_latency_ms"] >= 0


def test_source_runtime_and_sequence_mismatch_are_blocked(monkeypatch):
    radar = _radar()
    radar["source_runtime_instance_id"] = "other-source"
    radar["source_sequence"] = 2
    radar["expected_source_repo_sha"] = "c" * 40
    _patch(monkeypatch, radar=radar)
    result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
    assert result["symbols"] == {}
    assert result["status"] == "BLOCKED"
    assert "SOURCE_REPO_SHA_MISMATCH" in result["reasons"]
    assert "SOURCE_RUNTIME_ID_MISMATCH" in result["reasons"]
    assert "SOURCE_SEQUENCE_NOT_ALIGNED" in result["reasons"]
    assert result["radar_admission"] == "BLOCKED"


def test_unfresh_or_invalid_source_never_produces_assessment(monkeypatch):
    market = _market()
    market["status"] = "STALE"
    _patch(monkeypatch, market=market)
    result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
    assert result["ok"] is False
    assert result["symbols"] == {}
    assert "MARKET_SOURCE_NOT_FRESH_AND_VALID" in result["reasons"]


def test_missing_symbol_blocks_instead_of_inventing_quote(monkeypatch):
    _patch(monkeypatch)
    result = module.read_us_fast_research_brief(["NVDA"], now_utc=NOW)
    assert result["ok"] is False
    assert "US.NVDA" in result["missing_symbols"]
    assert result["symbols"] == {}


def test_malformed_or_oversized_requests_rejected_before_any_source_read(monkeypatch):
    calls = _patch(monkeypatch)
    for values in (["AMD"] * 9, ["HK.00700"], ["AMD", ""], []):
        result = module.read_us_fast_research_brief(values, now_utc=NOW)
        assert result["ok"] is False
        assert result["status"] == "INVALID_ARGUMENT"
    assert calls == {"market": 0, "radar": 0}


def test_empty_default_uses_available_readonly_symbols_without_prior_chat_state(monkeypatch):
    calls = _patch(monkeypatch)
    result = module.read_us_fast_research_brief(now_utc=NOW)
    assert result["ok"] is True
    assert list(result["symbols"]) == ["US.AMD"]
    assert calls == {"market": 1, "radar": 1}


def test_unproven_bar_closure_stays_unproven_and_never_grants_trade(monkeypatch):
    _patch(monkeypatch)
    result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
    assert result["provenance"]["source_bar_closure"] == "UNPROVEN"
    assert result["radar_admission"] == "BLOCKED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["trading_authority"] is False


def test_fast_brief_refuses_fresh_heartbeat_with_blocked_source_poll(monkeypatch):
    radar = _radar()
    radar["poll_status"] = "BLOCKED"
    _patch(monkeypatch, radar=radar)
    result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert "RADAR_CURRENT_POLL_NOT_VALID" in result["reasons"]
    assert result["provenance"]["radar_poll_status"] == "BLOCKED"
    assert result["symbols"] == {}
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_fast_brief_refuses_unknown_or_absent_radar_poll_status(monkeypatch):
    for status in ("UNKNOWN", None, "SOURCE_EXPORT_STALE", "DEGRADED"):
        radar = _radar()
        radar["poll_status"] = status
        _patch(monkeypatch, radar=radar)
        result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
        assert result["status"] == "BLOCKED"
        assert result["symbols"] == {}
        assert "RADAR_CURRENT_POLL_NOT_VALID" in result["reasons"]


def test_fast_brief_still_accepts_source_unchanged_only_as_research(monkeypatch):
    radar = _radar()
    radar["poll_status"] = "UNCHANGED"
    _patch(monkeypatch, radar=radar)
    result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
    assert result["ok"] is True
    assert result["status"] == "ALIGNED_RESEARCH_ONLY"
    assert result["can_confirm_signal"] is False
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["radar_admission"] == "BLOCKED"

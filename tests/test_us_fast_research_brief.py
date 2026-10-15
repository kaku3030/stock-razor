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



def test_quick_scan_one_cache_read_and_compact_multitimeframe_research(monkeypatch):
    calls = _patch(monkeypatch)
    result = module.read_us_quick_scan(["AMD"], now_utc=NOW)
    assert calls == {"market": 1, "radar": 1}
    assert result["ok"] is True
    assert result["status"] == "ALIGNED_RESEARCH_ONLY"
    assert result["provider_requests"] == 0
    assert result["live_trade"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["can_confirm_signal"] is False
    assert result["source"]["sequence"] == 3
    amd = result["symbols"]["US.AMD"]
    assert amd["bars"]["1m"]["close"] == 163
    assert amd["bars"]["1m"]["is_closed"] is True
    assert amd["bars"]["15m"] is None
    assert amd["trend"]["daily"]["trend"] == "up"
    assert amd["trend"]["15m"]["trend"] == "down"
    assert amd["support_levels"] == [159]
    assert amd["signal_permission"] == "BLOCKED"
    assert "indicators" not in str(result)
    assert result["read_latency_ms"] >= 0


def test_quick_scan_blocks_misaligned_and_stale_without_exposing_research(monkeypatch):
    radar = _radar()
    radar["source_sequence"] = 2
    calls = _patch(monkeypatch, radar=radar)
    result = module.read_us_quick_scan(["AMD"], now_utc=NOW)
    assert calls == {"market": 1, "radar": 1}
    assert result["ok"] is False
    assert result["symbols"] == {}
    assert "SOURCE_SEQUENCE_NOT_ALIGNED" in result["reasons"]
    assert result["live_trade"] is False


def test_quick_scan_blocks_invalid_symbols_before_reading(monkeypatch):
    calls = _patch(monkeypatch)
    result = module.read_us_quick_scan(["HK.00700"], now_utc=NOW)
    assert result["ok"] is False
    assert result["status"] == "INVALID_ARGUMENT"
    assert result["symbols"] == {}
    assert calls == {"market": 0, "radar": 0}


def test_quick_scan_preserves_partial_bar_flags(monkeypatch):
    market = _market()
    market["symbols"]["US.AMD"]["latest"]["15m"] = {
        "close": 165, "bar_end_utc": NOW.isoformat(),
        "is_closed": False, "is_complete": False,
        "quality_flags": ["PARTIAL_BAR", "MISSING_BAR"],
    }
    _patch(monkeypatch, market=market)
    result = module.read_us_quick_scan(["AMD"], now_utc=NOW)
    bar = result["symbols"]["US.AMD"]["bars"]["15m"]
    assert bar["is_closed"] is False
    assert bar["is_complete"] is False
    assert "PARTIAL_BAR" in bar["quality_flags"]
    assert result["can_confirm_signal"] is False


def test_one_step_publication_race_rereads_both_sources_without_provider(monkeypatch):
    first_market = _market()
    first_market["sequence"] = 4
    first_radar = _radar()
    aligned_radar = _radar()
    aligned_radar["source_sequence"] = 4
    counters = {"market": 0, "radar": 0, "sleep": 0}

    def read_market(*args, **kwargs):
        counters["market"] += 1
        return first_market

    def read_radar(*args, **kwargs):
        counters["radar"] += 1
        return first_radar if counters["radar"] == 1 else aligned_radar

    def fast_sleep(seconds):
        assert seconds == 0.05
        counters["sleep"] += 1

    monkeypatch.setattr(module, "read_us_market_snapshots", read_market)
    monkeypatch.setattr(module, "read_us_radar_analysis", read_radar)
    monkeypatch.setattr(module, "sleep", fast_sleep)

    result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
    assert counters == {"market": 2, "radar": 2, "sleep": 1}
    assert result["status"] == "ALIGNED_RESEARCH_ONLY"
    assert result["provenance"]["sequence_recheck_attempts"] == 1
    assert result["provenance"]["market_sequence"] == 4
    assert result["provenance"]["radar_source_sequence"] == 4
    assert result["provider_requests"] == 0
    assert result["trading_authority"] is False


def test_persistent_one_step_skew_stays_blocked_with_bounded_retries(monkeypatch):
    market = _market()
    market["sequence"] = 4
    radar = _radar()
    counts = _patch(monkeypatch, market=market, radar=radar)
    sleep_calls = []
    monkeypatch.setattr(module, "sleep", sleep_calls.append)

    result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
    assert counts == {"market": 3, "radar": 3}
    assert sleep_calls == [0.05, 0.05]
    assert result["status"] == "BLOCKED"
    assert result["symbols"] == {}
    assert "SOURCE_SEQUENCE_NOT_ALIGNED" in result["reasons"]
    assert result["provenance"]["sequence_recheck_attempts"] == 2
    assert result["can_confirm_signal"] is False


def test_large_skew_and_invalid_lineage_never_trigger_recheck(monkeypatch):
    market = _market()
    market["sequence"] = 5
    radar = _radar()
    calls = _patch(monkeypatch, market=market, radar=radar)
    monkeypatch.setattr(
        module, "sleep",
        lambda seconds: (_ for _ in ()).throw(AssertionError("unexpected retry")),
    )
    result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
    assert result["status"] == "BLOCKED"
    assert calls == {"market": 1, "radar": 1}

    # Even a one-step mismatch must never override SHA authenticity.
    market["sequence"] = 4
    radar["expected_source_repo_sha"] = "c" * 40
    result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
    assert result["status"] == "BLOCKED"
    assert "SOURCE_REPO_SHA_MISMATCH" in result["reasons"]
    assert calls == {"market": 2, "radar": 2}


def test_invalid_radar_poll_does_not_retry_sequence_race(monkeypatch):
    market = _market()
    market["sequence"] = 4
    radar = _radar()
    radar["poll_status"] = "UNKNOWN"
    calls = _patch(monkeypatch, market=market, radar=radar)
    monkeypatch.setattr(
        module, "sleep",
        lambda seconds: (_ for _ in ()).throw(AssertionError("unexpected retry")),
    )
    result = module.read_us_fast_research_brief(["AMD"], now_utc=NOW)
    assert calls == {"market": 1, "radar": 1}
    assert result["status"] == "BLOCKED"
    assert "RADAR_CURRENT_POLL_NOT_VALID" in result["reasons"]

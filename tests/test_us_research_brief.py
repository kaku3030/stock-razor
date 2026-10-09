from datetime import datetime, timezone

import data_provider.us_research_brief as reader

NOW = datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def _radar():
    return {
        "ok": True, "status": "PASS", "poll_status": "UNCHANGED",
        "worker_repo_sha": "b" * 40,
        "expected_source_repo_sha": SHA,
        "source_runtime_instance_id": "producer-1",
        "source_sequence": 77, "emitted_at_utc": NOW.isoformat(),
        "source_age_seconds": 1.0,
        "symbols": {"US.AMD": {
            "symbol": "US.AMD", "status": "RESEARCH_STATE", "reasons": [],
            "technical_state": {"technical": {
                "alignment": "mixed", "research_score": 64,
                "daily": {
                    "trend": "bullish", "momentum": "strengthening",
                    "confidence": 0.77, "quality": {"status": "ok", "warnings": []},
                    "indicators": {"rsi14": 65.1}},
                "hourly": {"trend": "neutral", "quality": {"status": "partial", "warnings": ["1h_partial_bar"]}},
                "intraday": {"trend": "bearish", "quality": {"status": "ok"}},
                "structure": {"support_levels": [102.5], "resistance_levels": [110.0]},
                "risk_flags": ["timeframe_disagreement"],
                "watch_conditions": ["Observe 110.0 resistance"],
            }}
        }},
    }


def _market():
    return {
        "ok": True, "status": "PASS", "repo_sha": SHA,
        "runtime_instance_id": "producer-1",
        "sequence": 77, "emitted_at_utc": NOW.isoformat(),
        "source_age_seconds": 2.0, "bar_closure": "UNPROVEN",
        "delivery_mode": "REALTIME",
        "symbols": {"US.AMD": {
            "provider": "futu", "feed": "opend",
            "health": {"signal_permission": "record_only"},
            "counts": {"1m": 120, "5m": 40, "15m": 24, "1h": 10},
            "latest": {
                "1m": {"close": 105.0, "quality_flags": ["partial_bar"]},
                "5m": None, "15m": None, "1h": None,
            },
        }},
    }


def _mock(monkeypatch, radar=None, market=None):
    r = _radar() if radar is None else radar
    m = _market() if market is None else market
    monkeypatch.setattr(reader, "read_us_radar_analysis", lambda symbols, **_: r)
    monkeypatch.setattr(reader, "read_us_market_snapshots", lambda symbols, **_: m)


def test_one_call_preserves_risk_quality_and_provenance(monkeypatch):
    _mock(monkeypatch)
    result = reader.read_us_market_brief(["AMD"], now_utc=NOW)
    assert result["status"] == "ALIGNED_RESEARCH"
    assert result["price_and_radar_sequence_aligned"] is True
    assert result["sources"]["radar"]["source_sequence"] == 77
    assert result["sources"]["canonical"]["sequence"] == 77
    assert result["symbols"]["US.AMD"]["daily"]["trend"] == "bullish"
    assert result["symbols"]["US.AMD"]["daily"]["indicators"]["rsi14"] == 65.1
    assert result["symbols"]["US.AMD"]["latest_bars"]["1m"]["close"] == 105.0
    assert result["symbols"]["US.AMD"]["risk_flags"] == ["timeframe_disagreement"]
    assert result["symbols"]["US.AMD"]["hourly"]["quality"]["warnings"] == ["1h_partial_bar"]
    assert result["radar_admission"] == "BLOCKED"
    assert result["signal_permission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert result["can_confirm_signal"] is False
    assert result["read_latency_ms"] >= 0


def test_never_combines_unrelated_price_and_radar_state(monkeypatch):
    market = _market()
    market["sequence"] = 78
    _mock(monkeypatch, market=market)
    result = reader.read_us_market_brief(["AMD"], now_utc=NOW)
    assert result["status"] == "MISALIGNED"
    assert result["symbols"] == {}
    assert "SOURCE_PROVENANCE_OR_SEQUENCE_MISMATCH" in result["reasons"]
    assert result["radar_admission"] == "BLOCKED"


def test_source_runtime_change_without_sequence_change_is_misaligned(monkeypatch):
    market = _market()
    market["runtime_instance_id"] = "producer-restarted"
    _mock(monkeypatch, market=market)
    result = reader.read_us_market_brief(["AMD"], now_utc=NOW)
    assert result["status"] == "MISALIGNED"
    assert result["symbols"] == {}


def test_old_radar_payload_with_no_runtime_identity_is_not_silently_aligned(monkeypatch):
    radar = _radar()
    radar.pop("source_runtime_instance_id")
    _mock(monkeypatch, radar=radar)
    assert reader.read_us_market_brief(["AMD"], now_utc=NOW)["status"] == "MISALIGNED"


def test_worker_block_or_source_failure_never_exposes_composite(monkeypatch):
    radar = _radar()
    radar["poll_status"] = "BLOCKED"
    _mock(monkeypatch, radar=radar)
    result = reader.read_us_market_brief(["AMD"], now_utc=NOW)
    assert result["status"] == "BLOCKED"
    assert result["symbols"] == {}
    market = _market()
    market["ok"] = False
    _mock(monkeypatch, market=market)
    assert reader.read_us_market_brief(["AMD"], now_utc=NOW)["status"] == "UNAVAILABLE"


def test_stale_and_missing_remain_degraded_not_authorized(monkeypatch):
    radar = _radar()
    radar["status"] = "STALE"
    _mock(monkeypatch, radar=radar)
    result = reader.read_us_market_brief(["AMD", "NVDA"], now_utc=NOW)
    assert result["status"] == "DEGRADED"
    assert "SOURCE_NOT_FRESH" in result["reasons"]
    assert "SYMBOLS_MISSING" in result["reasons"]
    assert result["missing_symbols"] == ["US.NVDA"]
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_bounded_symbol_request_rejects_before_sources_are_read(monkeypatch):
    def should_not_read(*a, **k):
        raise AssertionError("Unbounded requests must be rejected before IO")
    monkeypatch.setattr(reader, "read_us_radar_analysis", should_not_read)
    monkeypatch.setattr(reader, "read_us_market_snapshots", should_not_read)
    assert reader.read_us_market_brief(["AMD"] * 13)["status"] == "INVALID_ARGUMENT"
    assert reader.read_us_market_brief([""], now_utc=NOW)["status"] == "INVALID_ARGUMENT"

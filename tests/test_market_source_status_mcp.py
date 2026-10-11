"""Combined market-source status must never promote a TickFlow probe to a feed."""
from datetime import datetime, timezone
import json
from pathlib import Path

import data_provider.market_source_status as status

NOW = datetime(2026, 10, 10, 0, 0, tzinfo=timezone.utc)


def test_combined_sources_are_observational_only(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health", lambda **kw: {
        "ok": True, "status": "HEALTHY", "api_key": "SECRET",
        "raw_market_payload": "DO_NOT_EXPOSE"})
    monkeypatch.setattr(status, "read_cn_market_data", lambda *args, **kw: {
        "ok": True, "status": "PASS", "symbol": "159611.SZ",
        "rows": [{"close": 123}], "token": "SECRET"})
    monkeypatch.setattr(status, "read_tickflow_probe_health", lambda **kw: {
        "ok": True, "status": "PROBE_ONLY", "api_key": "SECRET",
        "operations": [{"name": "realtime_quote", "operation": "COMPLETED"}]})
    result = status.read_market_source_status(now_utc=NOW)
    assert result["ok"] is True and result["status"] == "OBSERVATION_ONLY"
    assert result["sources"]["us_opend"]["observation_healthy"] is True
    assert result["sources"]["cn_eastmoney_tencent"]["observation_available"] is True
    assert result["sources"]["cn_tickflow"]["isolated_probe_evidence_available"] is True
    assert result["sources"]["cn_tickflow"]["production_feed_connected"] is False
    assert result["provider_requests"] == 0
    assert result["model_inference_performed"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    text = json.dumps(result)
    assert "SECRET" not in text and "DO_NOT_EXPOSE" not in text
    assert "close" not in text and "operations" not in text


def test_tickflow_historical_observation_is_exposed_without_promoting_admission(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health", lambda **kw: {
        "ok": False, "status": "STALE"})
    monkeypatch.setattr(status, "read_cn_market_data", lambda *args, **kw: {
        "ok": False, "status": "NO_DATA"})
    monkeypatch.setattr(status, "read_tickflow_probe_health", lambda **kw: {
        "ok": True,
        "status": "PROBE_ONLY",
        "historical_kline_observation": {
            "operation": "COMPLETED",
            "row_count": 5,
            "symbol": "159611",
            "summary": {"period": "1d", "interval": "1d"},
        },
    })
    result = status.read_market_source_status(now_utc=NOW)
    observation = result["sources"]["cn_tickflow"]["historical_kline_observation"]
    assert observation["operation"] == "COMPLETED"
    assert observation["row_count"] == 5
    assert observation["summary"]["period"] == "1d"
    assert "timestamp_first" not in json.dumps(result)
    assert result["sources"]["cn_tickflow"]["data_admission"] == "BLOCKED"
    assert result["radar_admission"] == "BLOCKED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_historical_observation_defaults_to_not_requested(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health", lambda **kw: {
        "ok": False, "status": "STALE"})
    monkeypatch.setattr(status, "read_cn_market_data", lambda *args, **kw: {
        "ok": False, "status": "NO_DATA"})
    monkeypatch.setattr(status, "read_tickflow_probe_health", lambda **kw: {
        "ok": True, "status": "PROBE_ONLY"})
    result = status.read_market_source_status(now_utc=NOW)
    assert result["sources"]["cn_tickflow"]["historical_kline_observation"] == "NOT_REQUESTED"


def test_all_missing_is_fail_closed(monkeypatch):
    def missing(*args, **kwargs):
        raise OSError("SECRET")
    monkeypatch.setattr(status, "read_us_livefeed_health", missing)
    monkeypatch.setattr(status, "read_cn_market_data", missing)
    monkeypatch.setattr(status, "read_tickflow_probe_health", missing)
    result = status.read_market_source_status(now_utc=NOW)
    assert result["ok"] is False
    assert result["status"] == "UNAVAILABLE_OR_UNQUALIFIED"
    assert result["sources"]["cn_tickflow"]["status"] == "UNAVAILABLE"
    assert result["sources"]["cn_tickflow"]["historical_kline_observation"] == "NOT_REQUESTED"
    assert "SECRET" not in json.dumps(result)


def test_probe_only_does_not_imply_production_data(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health",
                        lambda **kw: {"ok": False, "status": "STALE"})
    monkeypatch.setattr(status, "read_cn_market_data",
                        lambda *args, **kw: {"ok": False, "status": "NO_DATA"})
    monkeypatch.setattr(status, "read_tickflow_probe_health",
                        lambda **kw: {"ok": True, "status": "PROBE_ONLY"})
    result = status.read_market_source_status(now_utc=NOW)
    assert result["ok"] is False
    assert result["status"] == "OBSERVATION_ONLY"
    assert result["sources"]["cn_tickflow"]["tickflow_to_radar_e2e"] == "NOT_VERIFIED"
    assert result["sources"]["cn_tickflow"]["data_admission"] == "BLOCKED"


def test_mcp_registered_and_no_direct_sdk():
    root = Path(__file__).resolve().parents[1]
    source = (root / "realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    assert "def get_market_source_status(" in source
    assert "return read_market_source_status(cn_symbol)" in source
    assert "import tickflow" not in status.__dict__
    assert "query_subscription(" not in Path(status.__file__).read_text(encoding="utf-8")


def test_reader_latency_is_local_only_and_cn_symbol_is_normalized(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health", lambda **kw: {
        "ok": True, "status": "HEALTHY"})
    monkeypatch.setattr(status, "read_cn_market_data", lambda *args, **kw: {
        "ok": True, "status": "PASS", "symbol": "159611"})
    monkeypatch.setattr(status, "read_tickflow_probe_health", lambda **kw: {
        "ok": True, "status": "PROBE_ONLY"})
    result = status.read_market_source_status("159611.SZ", now_utc=NOW)
    assert result["sources"]["cn_eastmoney_tencent"]["symbol"] == "159611.SZ"
    assert result["latency_scope"] == "LOCAL_CACHE_READERS_ONLY"
    assert result["end_to_end_latency"] == "NOT_MEASURED"
    assert result["market_data_freshness_latency"] == "NOT_MEASURED"
    assert result["read_latency_ms"] >= 0
    for source in result["sources"].values():
        assert isinstance(source["local_reader_latency_ms"], float)
        assert source["local_reader_latency_ms"] >= 0
    assert result["provider_requests"] == 0
    assert result["radar_admission"] == "BLOCKED"


def test_symbol_mismatch_does_not_echo_unrelated_symbol(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health", lambda **kw: {
        "ok": False, "status": "STALE"})
    monkeypatch.setattr(status, "read_cn_market_data", lambda *args, **kw: {
        "ok": True, "status": "PASS", "symbol": "159363"})
    monkeypatch.setattr(status, "read_tickflow_probe_health", lambda **kw: {
        "ok": False, "status": "UNAVAILABLE"})
    result = status.read_market_source_status("159611.SZ", now_utc=NOW)
    assert result["sources"]["cn_eastmoney_tencent"]["symbol"] is None
    assert result["end_to_end_latency"] == "NOT_MEASURED"


def test_tickflow_websocket_observation_is_visible_without_admission(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health", lambda **kw: {
        "ok": False, "status": "STALE"})
    monkeypatch.setattr(status, "read_cn_market_data", lambda *args, **kw: {
        "ok": False, "status": "NO_DATA"})
    monkeypatch.setattr(status, "read_tickflow_probe_health", lambda **kw: {
        "ok": True,
        "status": "PROBE_ONLY",
        "operations": [{
            "name": "websocket_quote_smoke",
            "operation": "OBSERVED",
            "quote_events": 6,
            "event_state": "PASS",
            "continuous_feed_qualified": False,
            "reconnect_resubscribe_evidence": "NOT_VERIFIED",
            "provider_secret": "NEVER_LEAK",
        }],
    })
    result = status.read_market_source_status(now_utc=NOW)
    websocket = result["sources"]["cn_tickflow"]["websocket_observation"]
    assert websocket["quote_events"] == 6
    assert websocket["continuous_feed_qualified"] is False
    assert websocket["reconnect_resubscribe_evidence"] == "NOT_VERIFIED"
    assert result["sources"]["cn_tickflow"]["data_admission"] == "BLOCKED"
    assert "NEVER_LEAK" not in json.dumps(result)


def test_tickflow_malformed_operations_fail_closed_without_mcp_failure(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health", lambda **kw: {
        "ok": False, "status": "STALE"})
    monkeypatch.setattr(status, "read_cn_market_data", lambda *args, **kw: {
        "ok": False, "status": "NO_DATA"})
    monkeypatch.setattr(status, "read_tickflow_probe_health", lambda **kw: {
        "ok": True, "status": "PROBE_ONLY",
        "operations": {"name": "websocket_quote_smoke", "provider_key": "SECRET"},
    })

    result = status.read_market_source_status(now_utc=NOW)

    assert result["sources"]["cn_tickflow"]["websocket_observation"] == "NOT_REQUESTED"
    assert result["sources"]["cn_tickflow"]["data_admission"] == "BLOCKED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert "SECRET" not in json.dumps(result)


def test_tickflow_historical_summary_is_strictly_allowlisted(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health", lambda **kw: {
        "ok": False, "status": "STALE"})
    monkeypatch.setattr(status, "read_cn_market_data", lambda *args, **kw: {
        "ok": False, "status": "NO_DATA"})
    monkeypatch.setattr(status, "read_tickflow_probe_health", lambda **kw: {
        "ok": True, "status": "PROBE_ONLY",
        "historical_kline_observation": {
            "operation": "COMPLETED",
            "period": "1d",
            "row_count": 5,
            "qualification": "NOT_VERIFIED",
            "provider_secret": "NEVER_LEAK",
            "summary": {
                "sample_count": 5,
                "period": "1d",
                "timestamp_monotonicity": "STRICTLY_INCREASING",
                "ohlcv_range_valid": True,
                "entitlement_evidence": "UNKNOWN",
                "freshness": "NEVER_LEAK",
                "credentials": "NEVER_LEAK",
                "timestamp_first": 12345,
            },
        },
    })
    result = status.read_market_source_status(now_utc=NOW)

    observation = result["sources"]["cn_tickflow"]["historical_kline_observation"]
    assert observation["row_count"] == 5
    assert observation["summary"]["timestamp_monotonicity"] == "STRICTLY_INCREASING"
    assert observation["summary"]["ohlcv_range_valid"] is True
    assert "freshness" not in observation["summary"]
    assert "NEVER_LEAK" not in json.dumps(result)
    assert "timestamp_first" not in json.dumps(result)
    assert result["sources"]["cn_tickflow"]["production_feed_connected"] is False


def test_healthy_us_worker_does_not_qualify_stale_market_snapshot(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health", lambda **kw: {
        "ok": True,
        "status": "HEALTHY",
        "repo_sha": "a" * 40,
        "canonical_snapshot_status": "STALE",
        "bar_closure_proven": False,
    })
    monkeypatch.setattr(status, "read_cn_market_data", lambda *args, **kw: {
        "ok": False,
        "status": "NO_DATA",
        "repo_sha": "INVALID_PUBLIC_SECRET",
    })
    monkeypatch.setattr(status, "read_tickflow_probe_health", lambda **kw: {
        "ok": True,
        "status": "PROBE_ONLY",
        "repo_sha": "c" * 40,
    })
    result = status.read_market_source_status(now_utc=NOW)

    us = result["sources"]["us_opend"]
    assert us["status"] == "HEALTHY"
    assert us["worker_heartbeat_healthy"] is True
    assert us["source_revision"] == "a" * 40
    assert us["canonical_snapshot_status"] == "STALE"
    assert us["canonical_snapshot_recent"] is False
    assert us["bar_closure_proven"] is False
    assert us["realtime_signal_permission"] == "BLOCKED"
    assert result["sources"]["cn_eastmoney_tencent"]["source_revision"] == "UNKNOWN"
    assert result["sources"]["cn_tickflow"]["source_revision"] == "c" * 40
    assert "INVALID_PUBLIC_SECRET" not in json.dumps(result)
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_recent_cache_and_proven_closure_do_not_automatically_authorize_signals(monkeypatch):
    monkeypatch.setattr(status, "read_us_livefeed_health", lambda **kw: {
        "ok": True,
        "status": "HEALTHY",
        "repo_sha": "b" * 40,
        "canonical_snapshot_status": "PASS",
        "bar_closure_proven": True,
    })
    monkeypatch.setattr(status, "read_cn_market_data", lambda *args, **kw: {
        "ok": False, "status": "NO_DATA"})
    monkeypatch.setattr(status, "read_tickflow_probe_health", lambda **kw: {
        "ok": False, "status": "UNAVAILABLE"})
    result = status.read_market_source_status(now_utc=NOW)
    us = result["sources"]["us_opend"]

    assert us["canonical_snapshot_recent"] is True
    assert us["bar_closure_proven"] is True
    assert us["realtime_signal_permission"] == "BLOCKED"
    assert us["provider_to_radar_e2e"] == "NOT_VERIFIED"
    assert result["source_arbiter_admission"] == "BLOCKED"

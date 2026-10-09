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

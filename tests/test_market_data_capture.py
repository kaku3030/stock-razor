from datetime import datetime, timezone
import hashlib
import json

import pytest

from src.services.strategy_lab.market_data_capture import MarketDataCapture, load_recorded_capture


def test_offline_capture_freezes_csv_with_explicit_provenance():
    capture = MarketDataCapture("baostock", "history-k", "baostock-adapter-v1", "CN", datetime(2026, 9, 13, tzinfo=timezone.utc), datetime(2026, 9, 13, tzinfo=timezone.utc), "Asia/Shanghai", "unadjusted", "symbol,date,open,high,low,close,volume\nsh.600000,2020-01-02,1,2,1,2,3\n")
    capsule = capture.to_capsule("cn-eod", "v1")
    assert capsule.source_id == "baostock"
    assert len(capsule.events) == 1


def test_recorded_capture_loader_verifies_manifest(tmp_path):
    csv_text = "symbol,date,open,high,low,close,volume\nSPY,2026-01-02,1,2,1,2,3\n"
    csv_path = tmp_path / "spy.csv"
    manifest_path = tmp_path / "spy.csv.manifest.json"
    csv_path.write_text(csv_text, encoding="utf-8")
    manifest_path.write_text(json.dumps({"source_id": "yfinance", "market": "us", "endpoint_id": "history_eod", "retrieved_at": "2026-09-13T00:00:00+00:00", "raw_sha256": hashlib.sha256(csv_text.encode()).hexdigest(), "adjustment": "unadjusted", "status": "CAPTURED_NOT_APPROVED"}), encoding="utf-8")
    assert load_recorded_capture(csv_path, manifest_path).source_id == "yfinance"
    manifest_path.write_text(manifest_path.read_text().replace("CAPTURED_NOT_APPROVED", "CAPTURE_BLOCKED"), encoding="utf-8")
    with pytest.raises(ValueError, match="not approved"):
        load_recorded_capture(csv_path, manifest_path)

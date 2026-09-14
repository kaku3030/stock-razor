import hashlib
import json
import sys

import pytest

from scripts.approve_research_capture import main
from src.services.strategy_lab.market_data_capture import load_recorded_capture


def _write_capture(tmp_path, payload=b"symbol,date,open,high,low,close,volume\nSPY,2025-01-01,1,2,0.5,1.5,100\n"):
    csv_path = tmp_path / "capture.csv"
    manifest_path = tmp_path / "capture.csv.manifest.json"
    csv_path.write_bytes(payload)
    manifest_path.write_text(json.dumps({
        "status": "CAPTURED_NOT_APPROVED",
        "raw_sha256": hashlib.sha256(payload).hexdigest(),
        "source_id": "test",
        "endpoint_id": "history_eod",
        "market": "us",
        "retrieved_at": "2026-01-01T00:00:00+00:00",
        "adjustment": "unadjusted",
    }), encoding="utf-8")
    return csv_path, manifest_path


def test_approval_records_auditable_pit_fields(tmp_path, monkeypatch):
    csv_path, manifest_path = _write_capture(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "approve_research_capture.py", "--csv", str(csv_path),
        "--manifest", str(manifest_path), "--approver", "reviewer-1",
        "--reason", "PIT review completed",
    ])
    assert main() == 0
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "PIT_APPROVED"
    assert manifest["pit_approved_by"] == "reviewer-1"
    assert manifest["pit_approval_reason"] == "PIT review completed"


def test_approval_rejects_hash_mismatch(tmp_path, monkeypatch):
    csv_path, manifest_path = _write_capture(tmp_path)
    csv_path.write_bytes(csv_path.read_bytes() + b"tampered")
    monkeypatch.setattr(sys, "argv", [
        "approve_research_capture.py", "--csv", str(csv_path),
        "--manifest", str(manifest_path), "--approver", "reviewer-1",
        "--reason", "PIT review completed",
    ])
    with pytest.raises(ValueError, match="sha256 mismatch"):
        main()


def test_approved_capture_enters_strict_pit_mode(tmp_path, monkeypatch):
    csv_path, manifest_path = _write_capture(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "approve_research_capture.py", "--csv", str(csv_path),
        "--manifest", str(manifest_path), "--approver", "reviewer-1",
        "--reason", "PIT review completed",
    ])
    assert main() == 0
    capture = load_recorded_capture(csv_path, manifest_path, require_pit_approved=True)
    assert capture.source_id == "test"

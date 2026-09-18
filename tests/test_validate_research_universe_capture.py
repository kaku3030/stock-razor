import csv
import hashlib
import json
from pathlib import Path

from scripts.validate_research_universe_capture import main


def _write_capture(
    root: Path,
    *,
    status: str = "CAPTURED_NOT_APPROVED",
    tamper: bool = False,
    write_csv: bool = True,
    write_manifest: bool = True,
) -> None:
    csv_path = root / "cn_sh_600000.csv"
    if write_csv:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("symbol", "date", "open", "high", "low", "close", "volume"))
            writer.writeheader()
            writer.writerow({"symbol": "sh.600000", "date": "2026-01-02", "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": "100"})
            writer.writerow({"symbol": "sh.600000", "date": "2026-01-03", "open": "10.5", "high": "12", "low": "10", "close": "11", "volume": "120"})
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest() if write_csv else "0" * 64
    if tamper:
        digest = "0" * 64
    if write_manifest:
        (root / "cn_sh_600000.csv.manifest.json").write_text(json.dumps({
            "source_id": "baostock", "market": "cn", "endpoint_id": "history_eod",
            "raw_sha256": digest, "status": status,
            "retrieved_at": "2026-09-16T22:52:46+00:00",
        }), encoding="utf-8")


def _write_config(root: Path) -> Path:
    config = root / "config.json"
    config.write_text(json.dumps({"markets": {"cn": {"source_id": "baostock", "symbols": ["sh.600000"]}}}), encoding="utf-8")
    return config


def test_capture_validator_accepts_complete_pair(tmp_path, monkeypatch):
    _write_capture(tmp_path)
    config = _write_config(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate", "--config", str(config), "--input-dir", str(tmp_path)])
    assert main() == 0


def test_capture_validator_reports_captured_result(tmp_path, monkeypatch):
    _write_capture(tmp_path)
    config = _write_config(tmp_path)
    report = tmp_path / "evidence.json"
    monkeypatch.setattr("sys.argv", ["validate", "--config", str(config), "--input-dir", str(tmp_path), "--evidence-report", str(report)])
    assert main() == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["result_counts"] == {"CAPTURED_NOT_APPROVED": 1, "CAPTURE_BLOCKED": 0, "MISSING_UNAVAILABLE": 0}
    assert payload["results"][0]["result"] == "CAPTURED_NOT_APPROVED"


def test_capture_validator_rejects_hash_mismatch(tmp_path, monkeypatch):
    _write_capture(tmp_path, tamper=True)
    config = _write_config(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate", "--config", str(config), "--input-dir", str(tmp_path)])
    assert main() == 2


def test_capture_validator_rejects_blocked_manifest(tmp_path, monkeypatch):
    _write_capture(tmp_path, status="CAPTURE_BLOCKED", write_csv=False)
    config = _write_config(tmp_path)
    report = tmp_path / "evidence.json"
    monkeypatch.setattr("sys.argv", ["validate", "--config", str(config), "--input-dir", str(tmp_path), "--evidence-report", str(report)])
    assert main() == 2
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["results"][0]["result"] == "CAPTURE_BLOCKED"


def test_capture_validator_reports_missing_unavailable(tmp_path, monkeypatch):
    config = _write_config(tmp_path)
    report = tmp_path / "evidence.json"
    monkeypatch.setattr("sys.argv", ["validate", "--config", str(config), "--input-dir", str(tmp_path), "--evidence-report", str(report)])
    assert main() == 2
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["results"][0]["result"] == "MISSING_UNAVAILABLE"


def test_capture_validator_writes_evidence_report(tmp_path, monkeypatch):
    _write_capture(tmp_path)
    config = _write_config(tmp_path)
    report = tmp_path / "evidence.json"
    monkeypatch.setattr("sys.argv", ["validate", "--config", str(config), "--input-dir", str(tmp_path), "--evidence-report", str(report)])
    assert main() == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema"] == "radar-research-universe-evidence-v0.1"
    assert payload["pit_status"] == "RECORDED_CAPTURE_ONLY"
    assert payload["approval_required"] is True


def test_capture_validator_rejects_timestamp_without_timezone(tmp_path, monkeypatch):
    _write_capture(tmp_path)
    manifest = tmp_path / "cn_sh_600000.csv.manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["retrieved_at"] = "2026-09-16T22:52:46"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    config = _write_config(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate", "--config", str(config), "--input-dir", str(tmp_path)])
    assert main() == 2

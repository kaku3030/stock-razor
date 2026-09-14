import csv
import hashlib
import json
from pathlib import Path

from scripts.validate_research_universe_capture import main


def _write_capture(root: Path, *, status: str = "CAPTURED_NOT_APPROVED", tamper: bool = False) -> None:
    csv_path = root / "cn_sh_600000.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("symbol", "date", "open", "high", "low", "close", "volume"))
        writer.writeheader()
        writer.writerow({"symbol": "sh.600000", "date": "2026-01-02", "open": "10", "high": "11", "low": "9", "close": "10.5", "volume": "100"})
        writer.writerow({"symbol": "sh.600000", "date": "2026-01-03", "open": "10.5", "high": "12", "low": "10", "close": "11", "volume": "120"})
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    if tamper:
        digest = "0" * 64
    (root / "cn_sh_600000.csv.manifest.json").write_text(json.dumps({
        "source_id": "baostock", "market": "cn", "endpoint_id": "history_eod",
        "raw_sha256": digest, "status": status,
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


def test_capture_validator_rejects_hash_mismatch(tmp_path, monkeypatch):
    _write_capture(tmp_path, tamper=True)
    config = _write_config(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate", "--config", str(config), "--input-dir", str(tmp_path)])
    assert main() == 2


def test_capture_validator_rejects_blocked_manifest(tmp_path, monkeypatch):
    _write_capture(tmp_path, status="CAPTURE_BLOCKED")
    config = _write_config(tmp_path)
    monkeypatch.setattr("sys.argv", ["validate", "--config", str(config), "--input-dir", str(tmp_path)])
    assert main() == 2

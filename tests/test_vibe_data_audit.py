import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone

from src.services.strategy_lab.data_audit import audit_csv


FIELDS = [
    "time_key", "open", "high", "low", "close", "volume", "symbol", "source",
    "timezone", "session", "closed_bar_evidence", "provider_finality", "calendar",
]


def write_rows(path, count=60, **overrides):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for index in range(count):
            row = {
                "time_key": (datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc) + timedelta(minutes=index)).isoformat(),
                "open": "100", "high": "101", "low": "99", "close": "100.5", "volume": "1000",
                "symbol": "US.TEST", "source": "licensed-offline-capture", "timezone": "UTC",
                "session": "regular", "closed_bar_evidence": "VERIFIED", "provider_finality": "VERIFIED",
                "calendar": "XNYS",
            }
            row.update(overrides)
            writer.writerow(row)


def test_audit_separates_stale_from_replay_eligibility(tmp_path):
    path = tmp_path / "US.TEST.csv"
    write_rows(path)
    report = audit_csv(path, now=datetime(2026, 1, 7, tzinfo=timezone.utc))
    assert report["checks"]["freshness"] == "STALE"
    assert report["historical_replay"]["eligibility"] == "BLOCKED"
    assert report["hashes"]["source_file"].startswith("sha256:")
    assert report["hashes"]["rows"].startswith("sha256:")


def test_unknown_finality_or_naive_timestamp_blocks_replay(tmp_path):
    path = tmp_path / "US.TEST.csv"
    write_rows(path, provider_finality="UNKNOWN", time_key="2026-01-05 14:30:00")
    report = audit_csv(path)
    assert report["checks"]["provider_finality"] == "UNKNOWN"
    assert report["checks"]["parse_errors"]
    assert report["historical_replay"]["eligibility"] == "BLOCKED"


def test_duplicate_or_invalid_ohlcv_is_not_silently_repaired(tmp_path):
    path = tmp_path / "US.TEST.csv"
    write_rows(path, high="98")
    report = audit_csv(path)
    assert report["checks"]["ohlcv"] == "FAIL"
    assert report["checks"]["ohlcv_error_rows"]
    assert report["historical_replay"]["eligibility"] == "BLOCKED"


def _write_capture(tmp_path, *, verified: bool):
    path = tmp_path / "AAPL.csv"
    rows = [
        ["AAPL", "2024-03-08T16:00:00-05:00", 100, 102, 99, 101, 1000, "test", "America/New_York", "XNYS_REGULAR", "VERIFIED" if verified else "NOT_VERIFIED", "VERIFIED" if verified else "NOT_VERIFIED", "XNYS"],
        ["AAPL", "2024-03-11T16:00:00-04:00", 101, 103, 100, 102, 1100, "test", "America/New_York", "XNYS_REGULAR", "VERIFIED" if verified else "NOT_VERIFIED", "VERIFIED" if verified else "NOT_VERIFIED", "XNYS"],
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["symbol", "time_key", "open", "high", "low", "close", "volume", "source", "timezone", "session", "closed_bar_evidence", "provider_finality", "calendar"])
        writer.writerows(rows)
    raw_path = path.with_suffix(path.suffix + ".raw.json")
    raw_path.write_bytes(b"raw")
    path.with_suffix(path.suffix + ".manifest.json").write_text(json.dumps({"raw_payload_sha256": hashlib.sha256(b"raw").hexdigest(), "raw_payload_path": raw_path.name}), encoding="utf-8")
    return path


def test_audit_requires_finality_and_closure(tmp_path):
    result = audit_csv(_write_capture(tmp_path, verified=False))
    assert result["checks"]["dst"] == "PASS"
    assert result["checks"]["trading_calendar"] == "PASS"
    assert result["checks"]["raw_payload_hash"] == "PASS"
    assert result["historical_replay"]["eligibility"] == "BLOCKED"


def test_audit_can_pass_only_with_explicit_evidence(tmp_path):
    result = audit_csv(_write_capture(tmp_path, verified=True))
    assert result["historical_replay"]["eligibility"] == "PASS"

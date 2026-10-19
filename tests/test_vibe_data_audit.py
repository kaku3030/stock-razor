import csv
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
    assert report["historical_replay"]["eligibility"] == "PASS"
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

import csv
import hashlib
import json

from scripts.compare_recorded_captures import compare


def _capture(root, name, source, *, close_delta=0.0, adjustment="unadjusted", dates=("2026-01-02", "2026-01-03")):
    csv_path = root / f"{name}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("symbol", "date", "open", "high", "low", "close", "volume"))
        writer.writeheader()
        for index, day in enumerate(dates):
            close = 10.0 + index + close_delta
            writer.writerow({"symbol": "sh.600000", "date": day, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 100 + index})
    manifest_path = root / f"{name}.manifest.json"
    manifest_path.write_text(json.dumps({"source_id": source, "market": "cn", "adjustment": adjustment, "status": "CAPTURED_NOT_APPROVED", "raw_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest()}), encoding="utf-8")
    return csv_path, manifest_path


def test_cross_source_capture_validates(tmp_path):
    left, left_manifest = _capture(tmp_path, "left", "baostock")
    right, right_manifest = _capture(tmp_path, "right", "akshare")
    result = compare(left, left_manifest, right, right_manifest, minimum_overlap=1.0, maximum_price_rel_diff=0.02, maximum_volume_rel_diff=0.20)
    assert result["status"] == "VALIDATED"


def test_cross_source_price_divergence_is_rejected(tmp_path):
    left, left_manifest = _capture(tmp_path, "left", "baostock")
    right, right_manifest = _capture(tmp_path, "right", "akshare", close_delta=1.0)
    result = compare(left, left_manifest, right, right_manifest, minimum_overlap=1.0, maximum_price_rel_diff=0.02, maximum_volume_rel_diff=0.20)
    assert result["status"] == "DIVERGENT"


def test_cross_source_overlap_is_unknown(tmp_path):
    left, left_manifest = _capture(tmp_path, "left", "baostock")
    right, right_manifest = _capture(tmp_path, "right", "akshare", dates=("2026-02-02", "2026-02-03"))
    result = compare(left, left_manifest, right, right_manifest, minimum_overlap=0.95, maximum_price_rel_diff=0.02, maximum_volume_rel_diff=0.20)
    assert result["status"] == "UNKNOWN"

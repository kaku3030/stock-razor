"""Offline bar crosscheck: synthetic-only tests, no provider/network/secret access."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.tickflow_offline_bar_crosscheck import compare_files

CN = ZoneInfo("Asia/Shanghai")


def fixture(source, *, timeframe="15m", origin="SYNTHETIC", count=12):
    # 2026-10-09 is a weekday; 09:45..11:30 Shanghai are valid 15m ends.
    start = datetime(2026, 10, 9, 9, 45, tzinfo=CN)
    if timeframe == "60m":
        ends = [
            datetime(2026, 10, day, hour, minute, tzinfo=CN)
            for day in (8, 9) for hour, minute in
            ((10, 30), (11, 30), (14, 0), (15, 0))
        ]
    else:
        ends = [start + timedelta(minutes=15 * i) for i in range(count)]
    rows = []
    for i, stamp in enumerate(ends):
        price = 1.5 + i * .001
        rows.append({
            "bar_end_utc": stamp.astimezone(timezone.utc).isoformat(),
            "open": price, "high": price + .01,
            "low": price - .01, "close": price + .002,
            "volume": 10000 + i * 100,
        })
    return {
        "schema": "stock_razor_cn_offline_bar_fixture_v0_1",
        "fixture_origin": origin,
        "source": source, "symbol": "159611.SZ",
        "timeframe": timeframe,
        "timestamp_semantic": "BAR_END",
        "adjustment": "NONE", "volume_unit": "SHARES",
        "rows": rows,
    }


def write(tmp_path, filename, obj):
    path = tmp_path / filename
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def test_synthetic_agreement_is_not_real_market_evidence(tmp_path):
    a, b = fixture("TICKFLOW"), fixture("TENCENT")
    result = compare_files(write(tmp_path, "a.json", a),
                           write(tmp_path, "b.json", b))
    assert result["status"] == "SYNTHETIC_TEST_ONLY"
    assert result["ok"] is False
    assert result["aligned_bars"] == 12
    assert result["provider_requests"] == 0
    assert result["data_qualification"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_real_labeled_agreement_still_does_not_admit_radar(tmp_path):
    a, b = fixture("TICKFLOW", origin="REAL_CAPTURED"), fixture(
        "EASTMONEY", origin="REAL_CAPTURED")
    result = compare_files(write(tmp_path, "a.json", a),
                           write(tmp_path, "b.json", b))
    assert result["status"] == "MATCH_OBSERVATIONAL"
    assert result["ok"] is True
    assert result["data_qualification"] == "NOT_VERIFIED"
    assert result["bar_closure_qualification"] == "NOT_VERIFIED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["canonical_write"] is False


def test_price_volume_and_missing_bars_are_counted(tmp_path):
    a, b = fixture("TICKFLOW"), fixture("TENCENT")
    a["rows"][0]["close"] += .02
    a["rows"][1]["volume"] *= 2
    a["rows"].pop(2)
    result = compare_files(write(tmp_path, "a.json", a),
                           write(tmp_path, "b.json", b))
    assert result["status"] == "MISMATCH"
    assert result["mismatch_counts"]["close"] == 1
    assert result["mismatch_counts"]["volume"] == 1
    assert result["missing_in_tickflow"] == 1
    assert result["missing_in_reference"] == 0


def test_overlap_requirement_blocks_short_series(tmp_path):
    a, b = fixture("TICKFLOW", count=5), fixture("TENCENT", count=5)
    result = compare_files(write(tmp_path, "a.json", a),
                           write(tmp_path, "b.json", b))
    assert result["status"] == "INSUFFICIENT_OVERLAP"
    assert result["ok"] is False


@pytest.mark.parametrize("change", [
    lambda d: d.update(timestamp_semantic="BAR_START"),
    lambda d: d.update(adjustment="FORWARD"),
    lambda d: d.update(volume_unit="LOTS"),
    lambda d: d.update(symbol="INVALID"),
    lambda d: d["rows"][0].update(high=0.01),
    lambda d: d["rows"][0].update(volume=-1),
    lambda d: d["rows"][0].update(close=float("nan")),
    lambda d: d["rows"][0].update(bar_end_utc="2026-10-09T01:46:00+00:00"),
    lambda d: d["rows"][0].update(bar_end_utc="2026-10-09T09:45:00"),
    lambda d: d["rows"].append(dict(d["rows"][0])),
    lambda d: d["rows"].reverse(),
    lambda d: d.update(api_key="NEVER_EXPORT"),
])
def test_invalid_fixture_fails_closed_without_echoing_payload(tmp_path, change):
    a, b = fixture("TICKFLOW"), fixture("TENCENT")
    change(a)
    result = compare_files(write(tmp_path, "a.json", a),
                           write(tmp_path, "b.json", b))
    assert result["status"] == "BLOCKED"
    assert result["ok"] is False
    assert "NEVER_EXPORT" not in json.dumps(result)
    assert result["radar_admission"] == "BLOCKED"


def test_60m_session_end_validation(tmp_path):
    a, b = fixture("TICKFLOW", timeframe="60m"), fixture("TENCENT", timeframe="60m")
    result = compare_files(write(tmp_path, "a.json", a),
                           write(tmp_path, "b.json", b), min_overlap=8)
    assert result["status"] == "SYNTHETIC_TEST_ONLY"
    a["rows"][0]["bar_end_utc"] = "2026-10-08T03:00:00+00:00"
    result = compare_files(write(tmp_path, "a.json", a),
                           write(tmp_path, "b.json", b), min_overlap=8)
    assert result["status"] == "BLOCKED"


def test_source_and_timeframe_mismatch_fail_closed(tmp_path):
    a, b = fixture("TICKFLOW"), fixture("TICKFLOW")
    result = compare_files(write(tmp_path, "a.json", a),
                           write(tmp_path, "b.json", b))
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "SOURCE_OR_SYMBOL_TIMEFRAME_MISMATCH"


def test_reader_does_not_call_network_or_write_canonical():
    source = (Path(__file__).resolve().parents[1] /
              "scripts/tickflow_offline_bar_crosscheck.py").read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "import tickflow" not in source
    assert "from futu" not in source
    assert "canonical_write" in source
    assert "provider_requests" in source

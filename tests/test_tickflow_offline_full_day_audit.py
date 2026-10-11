"""End-to-end composition tests use synthetic fixture bars only."""
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sys

from scripts.tickflow_offline_full_day_audit import audit_offline_full_day, main

CST = timezone(timedelta(hours=8))
DAY = date(2026, 10, 9)


def fixture(source, *, tf="15m", origin="REAL_CAPTURED", date_value=DAY):
    step = int(tf.removesuffix("m"))
    rows = []
    idx = 0
    for hour, minute in ((9, 30), (13, 0)):
        opening = datetime.combine(date_value, time(hour, minute), tzinfo=CST)
        for minutes_elapsed in range(step, 121, step):
            stamp = opening + timedelta(minutes=minutes_elapsed)
            close = 2 + idx * 0.001
            rows.append({
                "bar_end_utc": stamp.astimezone(timezone.utc).isoformat(),
                "open": close,
                "high": close + 0.01,
                "low": close - 0.01,
                "close": close + 0.001,
                "volume": 10000 + idx * 100,
            })
            idx += 1
    return {
        "schema": "stock_razor_cn_offline_bar_fixture_v0_1",
        "fixture_origin": origin,
        "source": source,
        "symbol": "159611.SZ",
        "timeframe": tf,
        "timestamp_semantic": "BAR_END",
        "adjustment": "NONE",
        "volume_unit": "SHARES",
        "rows": rows,
    }


def write(tmp_path, key, doc):
    path = tmp_path / key
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


def compare(tmp_path, a, b, **opts):
    return audit_offline_full_day(
        write(tmp_path, "tick.json", a),
        write(tmp_path, "reference.json", b),
        trading_day=DAY,
        trading_session_confirmed=True,
        timestamp_semantic_verified=True,
        **opts,
    )


def test_full_day_15m_60m_real_labeled_match_still_review_only(tmp_path):
    for tf, count in (("15m", 16), ("60m", 4)):
        a, b = fixture("TICKFLOW", tf=tf), fixture("TENCENT", tf=tf)
        result = compare(tmp_path, a, b)
        assert result["status"] == "REVIEW_ONLY"
        assert result["expected_bars"] == count
        assert result["aligned_bars"] == count
        assert result["missing_bars"] == result["unexpected_bars"] == 0
        assert result["ohlcv_mismatch_fields"]["close"] == 0
        assert result["provider_requests"] == 0
        assert result["provider_quota_reserved"] == 0
        assert result["data_qualification"] == "NOT_VERIFIED"
        assert result["bar_closure_qualification"] == "NOT_VERIFIED"
        assert result["source_arbiter_admission"] == "BLOCKED"
        assert result["radar_admission"] == "BLOCKED"
        assert result["canonical_write"] is False
        assert not result["paper_auto_ready"] and not result["live_trade"]


def test_missing_timestamp_even_if_both_feeds_agree_is_rejected(tmp_path):
    a, b = fixture("TICKFLOW"), fixture("EASTMONEY")
    a["rows"].pop(2)
    b["rows"].pop(2)
    result = compare(tmp_path, a, b)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "FULL_DAY_SESSION_GRID_MISMATCH"
    assert result["missing_bars"] == 1
    assert result["aligned_bars"] == 15


def test_ohlcv_price_disagreement_is_independently_blocked(tmp_path):
    a, b = fixture("TICKFLOW"), fixture("TENCENT")
    a["rows"][4]["close"] += 0.1
    result = compare(tmp_path, a, b)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "BAR_PARITY_OR_OVERLAP_MISMATCH"


def test_invalid_lunch_bar_and_wrong_day_fail_closed(tmp_path):
    a, b = fixture("TICKFLOW"), fixture("TENCENT")
    extra = dict(a["rows"][7])
    extra["bar_end_utc"] = datetime.combine(DAY, time(12, 15), tzinfo=CST).astimezone(
        timezone.utc
    ).isoformat()
    a["rows"].insert(8, extra)
    b["rows"].insert(8, dict(extra))
    result = compare(tmp_path, a, b)
    assert result["status"] == "BLOCKED"
    a, b = fixture("TICKFLOW", date_value=date(2026, 10, 8)), fixture(
        "TENCENT", date_value=date(2026, 10, 8)
    )
    result = compare(tmp_path, a, b)
    assert result["status"] == "BLOCKED"


def test_synthetic_origin_does_not_count_as_provider_proof(tmp_path):
    a, b = fixture("TICKFLOW", origin="SYNTHETIC"), fixture(
        "TENCENT", origin="SYNTHETIC"
    )
    result = compare(tmp_path, a, b)
    assert result["status"] == "SYNTHETIC_TEST_ONLY"
    assert result["provenance_verified"] is False
    assert result["data_qualification"] == "NOT_VERIFIED"


def test_missing_independent_calendar_and_semantic_evidence_blocks(tmp_path):
    a, b = fixture("TICKFLOW"), fixture("TENCENT")
    f1 = write(tmp_path, "a.json", a)
    f2 = write(tmp_path, "b.json", b)
    result = audit_offline_full_day(f1, f2, trading_day=DAY)
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "TRADING_SESSION_CONFIRMATION_MISSING"
    result = audit_offline_full_day(
        f1, f2, trading_day=DAY, trading_session_confirmed=True
    )
    assert result["reason"] == "TIMESTAMP_SEMANTIC_NOT_VERIFIED"
    assert result["provider_requests"] == 0


def test_wrong_source_bad_units_and_untrusted_extra_field_rejected(tmp_path):
    a, b = fixture("TICKFLOW"), fixture("TENCENT")
    a["api_key"] = "DO_NOT_LEAK"
    result = compare(tmp_path, a, b)
    assert result["status"] == "BLOCKED"
    assert "DO_NOT_LEAK" not in json.dumps(result)
    a.pop("api_key")
    b["source"] = "TICKFLOW"
    assert compare(tmp_path, a, b)["status"] == "BLOCKED"
    b["source"] = "TENCENT"
    b["volume_unit"] = "LOTS"
    assert compare(tmp_path, a, b)["status"] == "BLOCKED"


def test_cli_offline_only_prints_sanitized_aggregate(tmp_path, monkeypatch, capsys):
    a, b = fixture("TICKFLOW"), fixture("TENCENT")
    f1 = write(tmp_path, "a.json", a)
    f2 = write(tmp_path, "b.json", b)
    monkeypatch.setattr(sys, "argv", [
        "tickflow_offline_full_day_audit.py",
        "--tickflow-fixture", f1,
        "--reference-fixture", f2,
        "--trading-day", DAY.isoformat(),
        "--trading-session-confirmed",
        "--timestamp-semantic-verified",
    ])
    assert main() == 0
    out = capsys.readouterr().out
    assert '"status": "REVIEW_ONLY"' in out
    assert '"provider_requests": 0' in out
    assert '"open": 2.0' not in out


def test_composition_source_implementation_has_no_network_or_canonical_write():
    body = Path("scripts/tickflow_offline_full_day_audit.py").read_text(
        encoding="utf-8"
    )
    assert "import requests" not in body
    assert "import tickflow" not in body
    assert "from futu" not in body
    assert "canonical_write" in body

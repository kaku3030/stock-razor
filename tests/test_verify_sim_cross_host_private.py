"""Synthetic private US SIM files only; no broker, AWS or real account data."""
from datetime import datetime, timedelta, timezone
import json
import sys

from scripts.verify_sim_cross_host_private import (
    SCHEMA,
    verify_private_readbacks,
    main,
)


def payload(source, now, *, identity="999000123"):
    return {
        "schema": SCHEMA,
        "account_id": identity,
        "source": source,
        "account_generation": "synthetic-session-001",
        "observed_at_utc": now.isoformat(),
        "account_mode": "SIMULATE",
        "market": "US",
        "authenticated": True,
        "positions": [
            {"symbol": "US.TEST", "side": "LONG", "quantity": "5"},
            {"symbol": "US.FAKE", "side": "LONG", "quantity": "9"},
        ],
    }


def pair(tmp_path, now):
    w, a = tmp_path / "windows.json", tmp_path / "aws.json"
    w.write_text(json.dumps(payload("WINDOWS_LOCAL_OPEND", now)))
    a.write_text(json.dumps(payload("AWS_OPEND_SSM", now)))
    return w, a


def test_two_fresh_identical_private_accounts_only_match_for_review(tmp_path):
    now = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)
    w, a = pair(tmp_path, now)
    result = verify_private_readbacks(str(w), str(a), now_utc=now)
    assert result["status"] == "MATCHED_FOR_REVIEW"
    assert result["same_account_id"] and result["same_positions"]
    assert result["position_count"] == 2
    assert result["orders_sent"] == result["provider_calls"] == 0
    assert result["private_file_writes"] == 0
    assert not result["paper_auto_ready"]
    assert not result["broker_mutation_allowed"]
    assert not result["independent_realized_fills_proven"]
    raw = json.dumps(result)
    for secret in ("999000123", "US.TEST", "US.FAKE", "synthetic-session"):
        assert secret not in raw


def test_mismatched_accounts_do_not_expose_account_ids(tmp_path):
    now = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)
    w, a = pair(tmp_path, now)
    other = payload("AWS_OPEND_SSM", now, identity="111222333")
    a.write_text(json.dumps(other))
    result = verify_private_readbacks(str(w), str(a), now_utc=now)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "CROSS_HOST_SIM_ACCOUNT_ID_MISMATCH"
    assert "111222333" not in json.dumps(result)


def test_stale_or_different_positions_not_matched(tmp_path):
    now = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)
    w, a = pair(tmp_path, now)
    stale = payload("AWS_OPEND_SSM", now - timedelta(hours=2))
    a.write_text(json.dumps(stale))
    assert verify_private_readbacks(
        str(w), str(a), now_utc=now
    )["reason"] == "BROKER_READBACK_STALE_OR_FUTURE"

    diff = payload("AWS_OPEND_SSM", now)
    diff["positions"][0]["quantity"] = "6"
    a.write_text(json.dumps(diff))
    result = verify_private_readbacks(str(w), str(a), now_utc=now)
    assert result["reason"] == "CROSS_HOST_POSITION_MISMATCH"
    assert not result["same_positions"]


def test_malformed_and_duplicate_json_keys_block_without_echo(tmp_path):
    now = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)
    w, a = pair(tmp_path, now)
    w.write_text('{"account_id":"PRIVATE_SECRET","account_id":"ANOTHER_SECRET"}')
    result = verify_private_readbacks(str(w), str(a), now_utc=now)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "DUPLICATE_JSON_KEY"
    assert "PRIVATE_SECRET" not in json.dumps(result)


def test_unknown_keys_oversized_files_and_invalid_amounts_fail_closed(tmp_path):
    now = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)
    w, a = pair(tmp_path, now)
    unknown = payload("WINDOWS_LOCAL_OPEND", now)
    unknown["secret_token"] = "PRIVATE_TOKEN"
    w.write_text(json.dumps(unknown))
    assert verify_private_readbacks(
        str(w), str(a), now_utc=now
    )["reason"] == "PRIVATE_SCHEMA_INVALID"
    w.write_text("X" * 33000)
    assert verify_private_readbacks(
        str(w), str(a), now_utc=now
    )["reason"] == "PRIVATE_INPUT_TOO_LARGE"
    broken = payload("WINDOWS_LOCAL_OPEND", now)
    broken["positions"][0]["quantity"] = "NOT_A_DECIMAL"
    w.write_text(json.dumps(broken))
    assert verify_private_readbacks(
        str(w), str(a), now_utc=now
    )["reason"] == "POSITION_QUANTITY_INVALID"


def test_main_prints_only_bounded_sanitized_summary(tmp_path, monkeypatch, capsys):
    now = datetime.now(timezone.utc)
    w, a = pair(tmp_path, now)
    monkeypatch.setattr(sys, "argv", [
        "verify_sim_cross_host_private.py",
        "--windows-file", str(w), "--aws-file", str(a),
    ])
    assert main() == 0
    result = capsys.readouterr().out
    assert len(result) < 600
    assert "MATCHED_FOR_REVIEW" in result
    assert "999000123" not in result
    assert "US.TEST" not in result
    assert "orders_sent" in result


def test_missing_private_file_is_not_published(tmp_path):
    now = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)
    w, a = pair(tmp_path, now)
    result = verify_private_readbacks(
        str(tmp_path / "private-id-999.json"), str(a), now_utc=now
    )
    assert result["reason"] == "PRIVATE_INPUT_UNAVAILABLE"
    assert "private-id-999.json" not in json.dumps(result)


def test_recursive_private_json_is_sanitized_instead_of_traceback(tmp_path):
    now = datetime(2026, 10, 12, 3, tzinfo=timezone.utc)
    w, a = pair(tmp_path, now)
    w.write_text("[" * 1200 + "0" + "]" * 1200)
    result = verify_private_readbacks(str(w), str(a), now_utc=now)
    assert result["status"] == "BLOCKED"
    assert result["reason"] == "PRIVATE_INPUT_INVALID"
    assert "account_id" not in json.dumps(result)

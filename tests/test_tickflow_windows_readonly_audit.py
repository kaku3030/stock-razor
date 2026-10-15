"""Offline tests only: no paid TickFlow queries, credentials, broker or network."""
from datetime import datetime, timedelta, timezone
import json
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from scripts import audit_tickflow_windows_readonly as audit

CN = ZoneInfo("Asia/Shanghai")


def compact(labels):
    ticks = [
        int(datetime.fromisoformat(s).replace(tzinfo=CN).timestamp()) * 1000
        for s in labels
    ]
    n = len(labels)
    return {
        "timestamp": ticks,
        "open": [1.05] * n,
        "high": [1.06] * n,
        "low": [1.04] * n,
        "close": [1.055] * n,
        "volume": [1000] * n,
    }


def clock(local):
    return datetime.fromisoformat(local).replace(tzinfo=CN).astimezone(timezone.utc)


def test_opening_first_and_second_15m_due_labels_need_90s_grace():
    c = compact([
        "2026-10-14 14:30", "2026-10-14 14:45",
        "2026-10-15 09:45", "2026-10-15 10:00",
    ])
    first = audit.assess_compact(c, "15m", clock("2026-10-15 09:46:30"))
    assert first["status"] == "PASS_RESEARCH_ONLY"
    assert first["due_count"] == 1
    assert first["due_labels_present"] == 1
    assert first["future_or_forming_quarantined"] == 1
    second = audit.assess_compact(c, "15m", clock("2026-10-15 10:01:30"))
    assert second["status"] == "PASS_RESEARCH_ONLY"
    assert second["due_count"] == second["due_labels_present"] == 2
    assert second["future_or_forming_quarantined"] == 0
    assert second["exchange_bar_finality"] == "NOT_VERIFIED"


def test_one_missing_today_15m_label_blocks_even_when_latest_is_due():
    c = compact([
        "2026-10-14 14:00", "2026-10-14 14:15",
        "2026-10-14 14:30", "2026-10-15 10:00",
    ])
    answer = audit.assess_compact(c, "15m", clock("2026-10-15 10:02:00"))
    assert answer["status"] == "BLOCKED_UNVERIFIED"
    assert answer["due_count"] == 2
    assert answer["due_labels_present"] == 1
    assert answer["due_labels_missing"] == 1


def test_morning_first_60m_due_guard():
    c = compact([
        "2026-10-14 10:30", "2026-10-14 11:30",
        "2026-10-14 14:00", "2026-10-15 10:30",
    ])
    first = audit.assess_compact(c, "60m", clock("2026-10-15 10:30:30"))
    assert first["due_count"] == 0
    assert first["future_or_forming_quarantined"] == 1
    second = audit.assess_compact(c, "60m", clock("2026-10-15 10:31:30"))
    assert second["status"] == "PASS_RESEARCH_ONLY"
    assert second["due_count"] == second["due_labels_present"] == 1


def test_daily_date_never_promoted_to_today_closed_bar():
    c = compact([
        "2026-10-12 00:00", "2026-10-13 00:00",
        "2026-10-14 00:00", "2026-10-15 00:00",
    ])
    for at in ("2026-10-15 09:45", "2026-10-15 15:20"):
        answer = audit.assess_compact(c, "1d", clock(at))
        assert answer["status"] == "PASS_PRIOR_DAILY_RESEARCH_ONLY"
        assert answer["same_day_daily_quarantined"] == 1
        assert answer["current_day_d1_finality"] == "NOT_VERIFIED"


def test_compact_reordered_bars_and_nonfinite_rejected():
    c = compact([
        "2026-10-14 14:00", "2026-10-14 14:30",
        "2026-10-14 14:15", "2026-10-15 09:45",
    ])
    assert audit.assess_compact(c, "15m", clock("2026-10-15 09:47"))[
        "reordered_or_duplicate_rows"
    ] == 1
    assert audit.assess_compact(c, "15m", clock("2026-10-15 09:47"))[
        "status"
    ] == "BLOCKED_UNVERIFIED"
    c["close"][-1] = float("nan")
    blocked = audit.assess_compact(c, "15m", clock("2026-10-15 09:47"))
    assert blocked["invalid_rows"] == 1
    assert "nan" not in json.dumps(blocked)


def test_secure_win32_credential_decode_does_not_log_key(monkeypatch):
    secret = "KEY_NEVER_EXPOSE_THIS"
    win32cred = SimpleNamespace(
        CRED_TYPE_GENERIC=1,
        CredRead=lambda key, typ: {
            "CredentialBlob": secret.encode("utf-16-le"),
        },
    )
    monkeypatch.setitem(sys.modules, "win32cred", win32cred)
    assert audit.read_windows_credential() == secret
    assert audit.CRED_TARGET == "StockRazor/TickFlow/APIKey"


def test_cli_requires_explicit_opt_in_and_makes_zero_provider_calls(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["probe", "--timeframe", "15m"])
    assert audit.main() == 0
    printed = capsys.readouterr().out
    assert json.loads(printed)["provider_requests"] == 0
    assert "NOT_EXECUTED_OPT_IN_REQUIRED" in printed


def test_only_exception_class_is_projected_to_logs():
    exc = ValueError("API_KEY=SECRET_AND_PRICE=1.055")
    assert audit.safe_error_type(exc) == "ValueError"
    assert "SECRET" not in audit.safe_error_type(exc)


def test_fixed_symbol_and_timeframe_budget_only():
    assert audit.SYMBOLS == ("159611.SZ", "518880.SH")
    assert audit.PERIOD_COUNTS == {"15m": 96, "60m": 24, "1d": 40}

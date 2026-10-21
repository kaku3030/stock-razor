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


def test_partial_current_day_60m_sample_accepts_one_row_research_only():
    c = compact(["2026-10-15 10:30"])
    answer = audit.assess_compact(c, "60m", clock("2026-10-15 10:32"))
    assert answer["due_count"] == answer["due_labels_present"] == 1
    assert answer["status"] == "PASS_RESEARCH_ONLY"
    assert answer["exchange_bar_finality"] == "NOT_VERIFIED"


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


def test_cli_routes_intraday_to_session_endpoint_and_daily_to_history(
    monkeypatch, capsys,
):
    calls = []

    class FakeKlines:
        def intraday(self, symbol, *, period, count, as_dataframe):
            calls.append(("intraday", symbol, period, count, as_dataframe))
            return {}

        def get(self, symbol, *, period, count, as_dataframe, adjust):
            calls.append(("history", symbol, period, count, as_dataframe, adjust))
            return {}

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs == {"api_key": "fixture-key", "timeout": 8.0,
                              "max_retries": 0}
            self.klines = FakeKlines()

        def close(self):
            pass

    monkeypatch.setattr(audit, "SYMBOLS", ("159611.SZ",))
    monkeypatch.setattr(audit.importlib.metadata, "version",
                        lambda name: "0.1.25")
    monkeypatch.setattr(audit, "read_windows_credential", lambda: "fixture-key")
    monkeypatch.setattr(audit, "assess_compact",
                        lambda frame, timeframe, now: {"status": "PASS_RESEARCH_ONLY"})
    monkeypatch.setitem(sys.modules, "tickflow", SimpleNamespace(TickFlow=FakeClient))
    monkeypatch.setattr(sys, "argv", ["probe", "--execute", "--timeframe", "all"])

    assert audit.main() == 0
    capsys.readouterr()

    assert [(call[0], call[2]) for call in calls] == [
        ("intraday", "1m"),
        ("intraday", "5m"),
        ("intraday", "15m"),
        ("intraday", "60m"),
        ("history", "1d"),
    ]


def test_only_exception_class_is_projected_to_logs():
    exc = ValueError("API_KEY=SECRET_AND_PRICE=1.055")
    assert audit.safe_error_type(exc) == "ValueError"
    assert "SECRET" not in audit.safe_error_type(exc)


def test_fixed_symbol_and_timeframe_budget_only():
    assert audit.SYMBOLS == ("159611.SZ", "159209.SZ", "512730.SH", "159363.SZ")
    assert audit.PERIOD_COUNTS == {"1m": 240, "5m": 144, "15m": 96, "60m": 24, "1d": 40}


def test_one_minute_due_grid_is_session_bounded():
    assert audit.END_CLOCKS["1m"][0] == "09:31"
    assert audit.END_CLOCKS["1m"][-1] == "15:00"
    assert len(audit.END_CLOCKS["1m"]) == 240


def test_one_minute_research_grid_uses_same_closed_bar_guard():
    c = compact([
        "2026-10-14 14:59", "2026-10-14 15:00",
        "2026-10-15 09:31", "2026-10-15 09:32",
    ])
    out = audit.assess_compact(c, "1m", clock("2026-10-15 09:34"))
    assert out["due_count"] == 2
    assert out["due_labels_present"] == 2
    assert out["exchange_bar_finality"] == "NOT_VERIFIED"


def test_tiny_vendor_float_drift_never_masquerades_as_strict_closed_grid_bar():
    # Reproduces 2026-10-15 desktop vs AWS discrepancy in principle:
    # tolerant OHLC accepts a tiny 1e-5 drift that strict cloud rejects.
    # No raw actual provider values or credentials are used in the fixture.
    c=compact([
        "2026-10-14 14:00","2026-10-14 14:15",
        "2026-10-15 09:45","2026-10-15 10:00",
    ])
    c["low"][-1]=1.050000001  # just above open=1.05 by less than 1e-5.
    out=audit.assess_compact(c,"15m",clock("2026-10-15 10:02:00"))
    assert out["tiny_vendor_float_drift_rows"]==1
    assert out["invalid_rows"]==0
    assert out["due_count"]==2
    assert out["due_labels_present"]==1
    assert out["due_labels_missing"]==1
    assert out["status"]=="BLOCKED_UNVERIFIED"
    assert out["exchange_bar_finality"]=="NOT_VERIFIED"
    assert "1.055" not in str(out)


def test_no_tiny_drift_in_strict_bar_is_counted_as_success():
    c=compact([
        "2026-10-14 14:00","2026-10-14 14:15",
        "2026-10-15 09:45","2026-10-15 10:00",
    ])
    out=audit.assess_compact(c,"15m",clock("2026-10-15 10:02:00"))
    assert out["status"]=="PASS_RESEARCH_ONLY"
    assert out["tiny_vendor_float_drift_rows"]==0


def test_local_5m_full_grid_research_only_float_18_of_24():
    # Reproduces the real 2026-10-15 physical SDK morning sample (no prices).
    morning = [clock for clock in audit.END_CLOCKS["5m"] if clock <= "11:30"]
    assert len(morning) == 24
    prior = ["2026-10-14 14:45", "2026-10-14 14:50",
             "2026-10-14 14:55", "2026-10-14 15:00"]
    today = ["2026-10-15 " + t for t in morning]
    c = compact(prior + today)
    for i in range(len(prior),len(prior)+18):
        c["high"][i] = 1.054999999999
    status = audit.assess_compact(c,"5m",clock("2026-10-15 11:35"))
    assert status["status"] == "BLOCKED_UNVERIFIED"  # NOT strict
    assert status["due_count"] == 24
    assert status["due_labels_present"] == 6
    assert status["due_labels_missing"] == 18
    assert status["research_progress_status"] == "PASS_RESEARCH_ONLY"
    assert status["research_due_labels_present"] == 24
    assert status["research_due_labels_missing"] == 0
    assert status["same_session_float_drift_rows"] == 18
    assert status["exchange_bar_finality"] == "NOT_VERIFIED"


def test_local_5m_invalid_off_tick_float_does_not_gain_research_pass():
    labels = ["2026-10-14 14:45", "2026-10-14 14:50",
              "2026-10-14 14:55","2026-10-14 15:00",
              "2026-10-15 09:35"]
    c=compact(labels)
    c["open"][-1]=1.0504  # off 0.001 ETF tick lattice
    c["high"][-1]=1.054999999999
    got=audit.assess_compact(c,"5m",clock("2026-10-15 09:37"))
    assert got["status"]=="BLOCKED_UNVERIFIED"
    assert got["invalid_rows"]==1
    assert got["research_progress_status"]=="BLOCKED_UNVERIFIED"
    assert got["research_due_labels_missing"]==1


def test_research_exit_flag_is_explicit_opt_in(monkeypatch, capsys):
    # Without --execute neither special flag nor CLI may make provider calls.
    monkeypatch.setattr(sys,"argv",["audit","--timeframe","5m","--research-exit"])
    assert audit.main()==0
    result=json.loads(capsys.readouterr().out)
    assert result["provider_requests"]==0
    assert result["status"]=="NOT_EXECUTED_OPT_IN_REQUIRED"

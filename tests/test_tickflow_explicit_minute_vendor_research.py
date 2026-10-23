"""Official vendor precision is an explicit research policy, never live admission."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from data_provider.cn_tickflow_research_cache import (
    normalize_bars, build_observation, atomic_publish, read_cn_tickflow_research_data,
)
from tests.test_tickflow_binary_precision_research import compact, Klines

NOW = datetime(2026, 10, 23, 1, 36, tzinfo=timezone.utc)


@pytest.mark.parametrize("high", [1.599999999, 1.599995, 1.59999])
def test_vendor_bound_is_explicit_and_preserves_original_prices(high):
    raw = compact(high)
    before = deepcopy(raw)
    assert normalize_bars(raw, "1m", now_utc=NOW, session_increment=True) == []
    bars = normalize_bars(raw, "1m", now_utc=NOW, session_increment=True,
                          vendor_precision_research=True)
    assert len(bars) == 4
    assert raw == before and bars[-1]["high"] == high
    assert all(b["ohlc_validation"] == "VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
               and b["bar_finality"] == "NOT_VERIFIED" and b["is_partial_bar"] for b in bars)


@pytest.mark.parametrize("high,op,volume", [
    (1.59998,1.5,100), (1.599995,1.50045,100), (1.599995,1.5,-1),
])
def test_research_flag_keeps_vendor_bound_lattice_and_numeric_guards(high,op,volume):
    raw = compact(high)
    raw["open"] = [op]*4
    raw["volume"] = [volume]*4
    assert normalize_bars(raw, "1m", now_utc=NOW, session_increment=True,
                          vendor_precision_research=True) == []


def test_explicit_minute_writer_reader_policy_and_strict_mode(tmp_path):
    class VendorKlines(Klines):
        def intraday(self, symbol, *, period, count, as_dataframe):
            if period == "1m":
                return compact(1.599995)
            return super().intraday(symbol,period=period,count=count,as_dataframe=as_dataframe)
    class Client:
        klines = VendorKlines()
    snap = build_observation(Client(),now_utc=NOW,repo_sha="a"*40,
                             sequence=1,include_supplemental=True)
    path = tmp_path / "cache.json"
    atomic_publish(str(path),snap)
    args = dict(path=str(path),now_utc=NOW,limit=1)
    result = read_cn_tickflow_research_data("159611.SZ","1m",
                                           research_mode="session_progress",**args)
    assert result["status"] == "PASS_RESEARCH_ONLY"
    assert result["rows"][0]["high"] == 1.599995
    assert result["ohlc_precision_scope"] == "VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    assert result["can_confirm_signal"] is False and result["live_trade"] is False
    assert result["radar_admission"] == "BLOCKED" and result["currentness"] == "UNPROVEN"
    strict = read_cn_tickflow_research_data("159611.SZ","1m",
                                           research_mode="historical_only",**args)
    assert strict["ok"] is False
    # An old/forged frame cannot claim this broader policy implicitly.
    snap["symbols"]["159611.SZ"]["1m"].pop("precision_policy")
    atomic_publish(str(path),snap)
    assert read_cn_tickflow_research_data("159611.SZ","1m",
                research_mode="session_progress",**args)["status"] == "INVALID_CACHE"


def test_windows_vendor_opt_in_keeps_strict_status_blocked():
    from scripts import audit_tickflow_windows_readonly as audit
    from tests.test_tickflow_windows_readonly_audit import compact as compact_windows, clock
    c = compact_windows(["2026-10-20 14:58", "2026-10-20 14:59",
                         "2026-10-21 11:24", "2026-10-21 11:25"])
    c["low"][-1] = 1.050000001
    t = clock("2026-10-21 11:27:00")
    assert audit.assess_compact(c,"1m",t)["research_due_labels_present"] == 1
    opt = audit.assess_compact(c,"1m",t,vendor_precision_research=True)
    assert opt["research_due_labels_present"] == 2
    assert opt["status"] == "BLOCKED_UNVERIFIED"
    assert opt["exchange_bar_finality"] == "NOT_VERIFIED"


def test_explicit_vendor_precision_waits_for_grace_and_rejects_missing_amount():
    raw = compact(1.599995)
    near = datetime(2026,10,23,1,34,30,tzinfo=timezone.utc)
    bars = normalize_bars(raw,"1m",now_utc=near,session_increment=True,
                           vendor_precision_research=True)
    assert [b["label"][-5:] for b in bars] == ["09:31","09:32","09:33"]
    raw["amount"] = [-1]*4
    assert normalize_bars(raw,"1m",now_utc=NOW,session_increment=True,
                           vendor_precision_research=True) == []

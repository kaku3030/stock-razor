"""Separate binary64 representation noise from substantive 1m price gaps."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from data_provider.cn_tickflow_research_cache import (
    atomic_publish, build_observation, normalize_bars, read_cn_tickflow_research_data,
)
from tests.test_cn_tickflow_research_cache import FakeKlines, frame

NOW = datetime(2026, 10, 23, 1, 36, tzinfo=timezone.utc)
FIELDS = ("timestamp", "open", "high", "low", "close", "volume", "amount")


def compact(high):
    df = frame("1m", "2026-10-23")
    df["high"] = high
    return {key: df[key].tolist() for key in FIELDS}


def test_current_minute_binary_noise_preserves_provider_prices():
    raw = compact(1.5999999999999994)
    before = deepcopy(raw)
    bars = normalize_bars(raw, "1m", now_utc=NOW, session_increment=True)
    assert len(bars) == 4
    assert raw == before
    assert bars[-1]["high"] == 1.5999999999999994
    assert all(b["ohlc_validation"] == "VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
               and b["is_partial_bar"] and b["bar_finality"] == "NOT_VERIFIED" for b in bars)


@pytest.mark.parametrize("high", [1.599999999, 1.599995, 1.598])
def test_non_binary_minute_gaps_remain_quarantined(high):
    reasons = {}
    assert normalize_bars(compact(high), "1m", now_utc=NOW,
                          session_increment=True, quarantine_counts=reasons) == []
    assert reasons == {"TODAY_HIGH_BELOW_BODY": 4}


def test_binary_noise_does_not_qualify_an_off_tick_other_field():
    raw = compact(1.5999999999999994)
    raw["open"] = [1.500000001] * 4
    assert normalize_bars(raw, "1m", now_utc=NOW, session_increment=True) == []


def test_binary_minute_still_waits_for_publish_grace():
    near = datetime(2026, 10, 23, 1, 34, 30, tzinfo=timezone.utc)
    bars = normalize_bars(compact(1.5999999999999994), "1m", now_utc=near,
                          session_increment=True)
    assert [b["label"][-5:] for b in bars] == ["09:31", "09:32", "09:33"]


class Klines(FakeKlines):
    def intraday(self, symbol, *, period, count, as_dataframe):
        if period == "1m":
            return compact(1.5999999999999994)
        return super().intraday(symbol, period=period, count=count, as_dataframe=as_dataframe)


def test_writer_reader_pipeline_and_forged_larger_gap(tmp_path):
    class Client:
        klines = Klines()
    snap = build_observation(Client(), now_utc=NOW, repo_sha="a"*40, sequence=1,
                             include_supplemental=True)
    path = tmp_path / "cache.json"
    atomic_publish(str(path), snap)
    args = dict(path=str(path), now_utc=NOW, research_mode="session_progress", limit=1)
    result = read_cn_tickflow_research_data("159611.SZ", "1m", **args)
    assert result["status"] == "PASS_RESEARCH_ONLY"
    assert result["rows"][0]["high"] == 1.5999999999999994
    assert result["currentness"] == "UNPROVEN"
    assert result["bar_finality"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED" and result["live_trade"] is False
    # A legacy frame cannot implicitly claim the broader vendor research policy.
    snap["symbols"]["159611.SZ"]["1m"].pop("precision_policy")
    snap["symbols"]["159611.SZ"]["1m"]["rows"][-1]["high"] = 1.599999999
    atomic_publish(str(path), snap)
    rejected = read_cn_tickflow_research_data("159611.SZ", "1m", **args)
    assert rejected["status"] == "INVALID_CACHE"


def test_windows_cloud_binary_subset_agrees_and_substantive_gap_stays_blocked():
    from scripts import audit_tickflow_windows_readonly as audit
    from data_provider.cn_tickflow_research_cache import _binary_etf_ohlc_shape_valid
    from tests.test_tickflow_windows_readonly_audit import compact as windows_compact, clock
    for low, expected in [(1.0500000000000003, True), (1.050000001, False),
                           (1.050005, False)]:
        values = (1.05, 1.07, low, 1.06)
        assert _binary_etf_ohlc_shape_valid(*values) is expected
        assert audit._binary_etf_ohlc_shape_valid(*values) is expected
        raw = windows_compact(["2026-10-20 14:58", "2026-10-20 14:59",
                               "2026-10-21 11:24", "2026-10-21 11:25"])
        raw["low"][-1] = low
        result = audit.assess_compact(raw, "1m", clock("2026-10-21 11:27:00"))
        assert result["research_due_labels_present"] == (2 if expected else 1)
        assert result["exchange_bar_finality"] == "NOT_VERIFIED"

"""Strictly turn sanitized historical OpenD bars into offline replay only."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.services.us_cloud_historical_session import (
    partition_historical_opend_us_15m,
    select_historical_full_60m_gate,
)

NY = ZoneInfo("America/New_York")


def response(day=date(2026, 10, 9)):
    first = datetime.combine(day, time(9, 30), NY).astimezone(timezone.utc)
    rows = []
    for i in range(26):
        start = first + timedelta(minutes=15*i)
        end = start + timedelta(minutes=15)
        rows.append({
            "symbol": "US.AMD", "market": "us", "asset_type": "stock",
            "timeframe": "15m", "session": "regular",
            "provider": "futu", "feed": "opend",
            "bar_start_utc": start.isoformat(), "bar_end_utc": end.isoformat(),
            "source_timestamp_utc": end.isoformat(),
            "received_at_utc": (end + timedelta(hours=2)).isoformat(),
            "open": 100+i, "high": 101+i, "low": 99+i, "close": 100+i,
            "volume": 100, "quality_flags": ["HISTORICAL_QUERY", "STALE"],
            "is_closed": True, "is_complete": True,
        })
    return {"ok": True, "status": "STALE", "bars": rows}


def test_stale_historical_full_us_rth_session_is_research_only():
    x = partition_historical_opend_us_15m(response(), symbol="AMD")
    assert len(x) == 1
    session = x[0]
    assert session.symbol == "AMD"
    assert session.exchange_local_date == "2026-10-09"
    assert len(session.bars) == 26
    assert session.historical_only is True
    assert session.live_currentness_verified is False
    assert session.source_identity_independently_verified is False
    assert session.external_broker_paper_verified is False
    assert session.paper_auto_ready is False
    assert session.radar_admission == "BLOCKED"
    assert session.live_trade is False


def test_winter_rth_uses_new_york_timezone_not_hardcoded_utc_clock():
    x = partition_historical_opend_us_15m(response(date(2026, 11, 9)), symbol="AMD")
    assert x[0].bars[0].start.hour == 14
    assert x[0].bars[-1].end.hour == 21


def test_two_unsorted_full_sessions_are_partitioned_chronologically():
    a = response(date(2026, 10, 9))
    b = response(date(2026, 10, 8))
    a["bars"] = a["bars"] + b["bars"]
    x = partition_historical_opend_us_15m(a, symbol="AMD")
    assert [session.exchange_local_date for session in x] == [
        "2026-10-08", "2026-10-09",
    ]


def test_must_not_launder_missing_bar_duplicate_or_partially_closed_sample():
    for mutate in (
        lambda x: x["bars"].pop(),
        lambda x: x["bars"].__setitem__(1, dict(x["bars"][0])),
        lambda x: x["bars"][3].update({"is_complete": False}),
        lambda x: x["bars"][3].update({"is_closed": "true"}),
    ):
        data = response()
        mutate(data)
        with pytest.raises(ValueError):
            partition_historical_opend_us_15m(data, symbol="AMD")


def test_provenance_and_historical_flags_are_not_optional():
    for patch in (
        {"provider": "unknown"}, {"feed": "sim"}, {"session": "afterhours"},
        {"symbol": "US.TSLA"}, {"timeframe": "5m"}, {"asset_type": "option"},
        {"quality_flags": ["STALE"]},
        {"quality_flags": ["HISTORICAL_QUERY", "UNKNOWN"]},
    ):
        data = response()
        data["bars"][0].update(patch)
        with pytest.raises(ValueError):
            partition_historical_opend_us_15m(data, symbol="AMD")


def test_fabricated_source_end_or_received_before_close_fails():
    d = response()
    d["bars"][0]["source_timestamp_utc"] = d["bars"][0]["bar_start_utc"]
    with pytest.raises(ValueError, match="SOURCE_TIMESTAMP"):
        partition_historical_opend_us_15m(d, symbol="AMD")
    d = response()
    d["bars"][0]["received_at_utc"] = d["bars"][0]["bar_start_utc"]
    with pytest.raises(ValueError, match="SOURCE_TIMESTAMP"):
        partition_historical_opend_us_15m(d, symbol="AMD")


def test_no_rows_no_success_status_no_symbol_match_fail_closed():
    a = response()
    a["bars"] = []
    with pytest.raises(ValueError):
        partition_historical_opend_us_15m(a, symbol="AMD")
    a = response()
    a["ok"] = False
    with pytest.raises(ValueError):
        partition_historical_opend_us_15m(a, symbol="AMD")
    with pytest.raises(ValueError):
        partition_historical_opend_us_15m(response(), symbol="NVD/A")


def hourly_response(day=date(2026, 10, 9)):
    start = datetime.combine(day, time(9, 30), NY).astimezone(timezone.utc)
    bars = []
    for i in range(7):
        a = start + timedelta(hours=i)
        end = a + timedelta(minutes=30 if i == 6 else 60)
        bars.append({
            "symbol": "US.AMD", "market": "us", "asset_type": "stock",
            "timeframe": "1h", "session": "regular",
            "provider": "futu", "feed": "opend",
            "bar_start_utc": a.isoformat(), "bar_end_utc": end.isoformat(),
            "source_timestamp_utc": end.isoformat(),
            "received_at_utc": (end + timedelta(hours=3)).isoformat(),
            "is_closed": True, "is_complete": True,
            "quality_flags": ["HISTORICAL_QUERY", "STALE"],
        })
    return {"ok": True, "status": "STALE", "bars": bars}


def test_final_30m_pseudo_hour_is_ignored_for_upstream_full_hour_gate():
    rows = hourly_response()
    cutoff = datetime(2026, 10, 9, 20, tzinfo=timezone.utc)
    gate = select_historical_full_60m_gate(
        rows, symbol="AMD", decision_as_of=cutoff, upstream_passed=True
    )
    assert gate.closed_bar_end == cutoff - timedelta(minutes=30)
    assert gate.bar_duration_minutes == 60
    assert gate.source == "futu/opend"
    assert gate.passed is True
    assert gate.bar_was_closed is True


def test_future_60m_bar_is_never_used_at_earlier_decision():
    rows = hourly_response()
    cutoff = datetime(2026, 10, 9, 15, tzinfo=timezone.utc)
    gate = select_historical_full_60m_gate(
        rows, symbol="AMD", decision_as_of=cutoff, upstream_passed=True
    )
    assert gate.closed_bar_end == datetime(2026, 10, 9, 14, 30, tzinfo=timezone.utc)


def test_future_1h_and_strange_hour_durations_fail_closed():
    a = hourly_response()
    a["bars"][0]["bar_end_utc"] = a["bars"][0]["bar_start_utc"]
    with pytest.raises(ValueError, match="HOURLY"):
        select_historical_full_60m_gate(
            a, symbol="AMD",
            decision_as_of=datetime(2026, 10, 9, 20, tzinfo=timezone.utc),
            upstream_passed=True,
        )


def test_unclear_hour_gate_arguments_and_no_full_hour_fail():
    with pytest.raises(ValueError, match="ARGUMENTS"):
        select_historical_full_60m_gate(
            hourly_response(), symbol="AMD",
            decision_as_of=datetime(2026, 10, 9, 20),
            upstream_passed=True,
        )
    with pytest.raises(ValueError, match="ARGUMENTS"):
        select_historical_full_60m_gate(
            hourly_response(), symbol="AMD",
            decision_as_of=datetime(2026, 10, 9, 20, tzinfo=timezone.utc),
            upstream_passed="true",
        )
    with pytest.raises(ValueError, match="NO_FULL"):
        select_historical_full_60m_gate(
            hourly_response(), symbol="AMD",
            decision_as_of=datetime(2026, 10, 9, 13, 30, tzinfo=timezone.utc),
            upstream_passed=True,
        )

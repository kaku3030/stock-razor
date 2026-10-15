from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from data_provider.market_data_adapter import Bar
from src.services.live_feed.us_intraday_closure import qualify_us_current_session_intraday_closure


ET = ZoneInfo("America/New_York")


def _bar(start, minutes):
    end = start + timedelta(minutes=minutes)
    return Bar(
        symbol="US.AMD", market="us", asset_type="stock", timeframe="15m" if minutes == 15 else "1h",
        bar_start=start, bar_end=end, open=1, high=1, low=1, close=1, volume=1,
        provider="futu", source_timestamp=end, received_at=end + timedelta(seconds=1),
        session="regular", is_closed=True, is_complete=True, feed="opend",
    )


def test_current_session_15m_and_60m_grids_are_pass_only_when_complete():
    as_of = datetime(2026, 10, 9, 16, 1, tzinfo=ET)
    bars = {"15m": [], "1h": []}
    start = datetime(2026, 10, 9, 9, 30, tzinfo=ET)
    for offset in range(0, 390, 15):
        bars["15m"].append(_bar(start + timedelta(minutes=offset), 15))
    for offset in range(0, 390, 60):
        bars["1h"].append(_bar(start + timedelta(minutes=offset), min(60, 390 - offset)))
    result = qualify_us_current_session_intraday_closure(bars, as_of=as_of)
    assert result["status"] == "PASS"
    assert result["timeframes"]["15m"]["expected_closed_count"] == 26
    assert result["timeframes"]["1h"]["expected_closed_count"] == 7


def test_missing_current_session_bar_stays_unknown_and_cannot_promote():
    as_of = datetime(2026, 10, 9, 10, 1, tzinfo=ET)
    result = qualify_us_current_session_intraday_closure({"15m": [], "1h": []}, as_of=as_of)
    assert result["status"] == "UNKNOWN"
    assert result["bar_closure_promotion_authorized"] is False


def _live_grids(as_of):
    start = datetime(2026, 10, 12, 9, 30, tzinfo=ET)
    # 13:30 ET has exactly 16 closed 15m and 4 closed 1h buckets.
    closed_15m = [_bar(start + timedelta(minutes=offset), 15)
                  for offset in range(0, 240, 15)]
    closed_1h = [_bar(start + timedelta(minutes=offset), 60)
                 for offset in range(0, 240, 60)]
    forming_15m = replace(
        _bar(start + timedelta(minutes=240), 15),
        is_closed=False, is_complete=False,
    )
    forming_1h = replace(
        _bar(start + timedelta(minutes=240), 60),
        is_closed=False, is_complete=False,
    )
    assert as_of == datetime(2026, 10, 12, 13, 41, tzinfo=ET)
    return {"15m": closed_15m + [forming_15m],
            "1h": closed_1h + [forming_1h]}


def test_intraday_current_forming_15m_and_1h_do_not_veto_ended_complete_grids():
    now = datetime(2026, 10, 12, 13, 41, tzinfo=ET)
    report = qualify_us_current_session_intraday_closure(_live_grids(now), as_of=now)
    assert report["status"] == "PASS"
    assert report["reason"] == "CURRENT_SESSION_15M_60M_CLOSED_GRIDS_COMPLETE"
    assert report["bar_closure_promotion_authorized"] is False
    for frame, count in (("15m", 16), ("1h", 4)):
        item = report["timeframes"][frame]
        assert item["status"] == "PASS"
        assert item["expected_closed_count"] == count
        assert item["observed_closed_count"] == count
        assert item["current_forming_excluded_count"] == 1
        assert item["missing_bar_starts"] == []
        assert item["invalid_bar_starts"] == []


def test_missing_ended_bucket_and_stale_forming_bucket_still_block():
    now = datetime(2026, 10, 12, 13, 41, tzinfo=ET)
    missing = _live_grids(now)
    missing["15m"].pop(5)
    result = qualify_us_current_session_intraday_closure(missing, as_of=now)
    assert result["status"] == "UNKNOWN"
    assert result["timeframes"]["15m"]["missing_bar_starts"]

    bad_ended = _live_grids(now)
    bad_ended["1h"][1] = replace(
        bad_ended["1h"][1], is_closed=False, is_complete=False,
    )
    report = qualify_us_current_session_intraday_closure(bad_ended, as_of=now)
    assert report["status"] == "UNKNOWN"
    assert report["timeframes"]["1h"]["invalid_bar_starts"]


def test_prematurely_closed_current_bar_and_bad_provenance_cannot_be_ignored():
    now = datetime(2026, 10, 12, 13, 41, tzinfo=ET)
    for bad_bar in (
        replace(_live_grids(now)["15m"][-1], is_closed=True, is_complete=True),
        replace(_live_grids(now)["15m"][-1], provider="other"),
        replace(_live_grids(now)["15m"][-1], feed="not-opend"),
    ):
        bars = _live_grids(now)
        bars["15m"][-1] = bad_bar
        result = qualify_us_current_session_intraday_closure(bars, as_of=now)
        assert result["status"] == "UNKNOWN"
        assert result["timeframes"]["15m"]["invalid_bar_starts"]
        assert result["timeframes"]["15m"]["current_forming_excluded_count"] == 0


def test_without_first_closed_1h_bucket_stays_unknown_during_session():
    now = datetime(2026, 10, 12, 10, 0, tzinfo=ET)
    start = datetime(2026, 10, 12, 9, 30, tzinfo=ET)
    bars = {
        "15m": [_bar(start, 15), _bar(start + timedelta(minutes=15), 15)],
        "1h": [replace(_bar(start, 60), is_closed=False, is_complete=False)],
    }
    result = qualify_us_current_session_intraday_closure(bars, as_of=now)
    assert result["status"] == "UNKNOWN"
    assert result["timeframes"]["15m"]["status"] == "PASS"
    assert result["timeframes"]["1h"]["status"] == "UNKNOWN"
    assert result["bar_closure_promotion_authorized"] is False


def test_duplicate_forming_bucket_or_wrong_timeframe_cannot_promote():
    now = datetime(2026, 10, 12, 13, 41, tzinfo=ET)
    duplicate = _live_grids(now)
    duplicate["15m"].append(duplicate["15m"][-1])
    report = qualify_us_current_session_intraday_closure(duplicate, as_of=now)
    assert report["status"] == "UNKNOWN"
    assert report["timeframes"]["15m"]["current_forming_excluded_count"] == 2
    assert report["timeframes"]["15m"]["invalid_bar_starts"]

    wrong_timeframe = _live_grids(now)
    wrong_timeframe["15m"][-1] = replace(
        wrong_timeframe["15m"][-1], timeframe="1h",
    )
    report = qualify_us_current_session_intraday_closure(wrong_timeframe, as_of=now)
    assert report["status"] == "UNKNOWN"
    assert report["timeframes"]["15m"]["current_forming_excluded_count"] == 0
    assert report["timeframes"]["15m"]["invalid_bar_starts"]


def test_postclose_historical_terminal_minute_does_not_prove_live_closure():
    as_of = datetime(2026, 10, 9, 16, 31, tzinfo=ET)
    start = datetime(2026, 10, 9, 9, 30, tzinfo=ET)
    bars_15m = [_bar(start + timedelta(minutes=i), 15) for i in range(0, 390, 15)]
    bars_1h = [
        _bar(start + timedelta(minutes=i), min(60, 390 - i))
        for i in range(0, 390, 60)
    ]
    bars_15m[-1] = replace(
        bars_15m[-1], quality_flags=("HISTORICAL_QUERY",),
    )
    bars_1h[-1] = replace(
        bars_1h[-1], quality_flags=("HISTORICAL_QUERY",),
    )
    result = qualify_us_current_session_intraday_closure(
        {"15m": bars_15m, "1h": bars_1h}, as_of=as_of
    )
    assert result["status"] == "UNKNOWN"
    assert result["bar_closure_promotion_authorized"] is False
    for frame in ("15m", "1h"):
        assert result["timeframes"][frame]["status"] == "UNKNOWN"
        assert result["timeframes"][frame]["invalid_bar_starts"]

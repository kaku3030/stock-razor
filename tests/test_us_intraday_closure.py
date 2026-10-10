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

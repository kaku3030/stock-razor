"""No-paid-call regressions for the 2026-10-11 TickFlow ¥199 monthly envelope."""
from dataclasses import replace

import pytest

from data_provider.tickflow_expert_capacity_plan import plan_tickflow_expert_capacity as plan


def universe(n):
    return tuple(f"{i:06d}.SZ" for i in range(1, n + 1))


@pytest.mark.parametrize(
    "endpoint,request_rate,batch",
    [
        ("realtime_quote_batch", 300, 500),
        ("daily_kline_batch", 120, 200),
        ("minute_kline_batch", 60, 200),
        ("minute_kline_single", 120, 1),
    ],
)
def test_advertised_account_rate_caps_are_preserved_without_provider_calls(
    endpoint, request_rate, batch,
):
    r = plan(("159611.SZ",), endpoint=endpoint)
    assert r.status == "REVIEW_ONLY"
    assert r.advertised_requests_per_minute == request_rate
    assert r.max_symbols_per_request == batch
    assert r.recommended_requests_per_minute == request_rate * 75 // 100
    assert r.provider_requests == r.quota_reserved == 0
    assert r.account_entitlement == "NOT_VERIFIED"
    assert r.shared_account_coordination == "NOT_IMPLEMENTED"
    assert r.source_arbiter_admission == r.radar_admission == "BLOCKED"
    assert r.data_qualification == "NOT_VERIFIED"
    assert not r.paper_auto_ready and not r.live_trade


def test_bulk_quote_sizing_for_5000_etfs_not_one_request_per_symbol():
    r = plan(universe(5000), endpoint="realtime_quote_batch")
    assert r.status == "REVIEW_ONLY"
    assert r.symbol_count == 5000
    assert r.max_symbols_per_request == 500
    assert r.planned_requests == 10
    assert r.advertised_requests_per_minute == 300
    assert r.recommended_requests_per_minute == 225
    assert r.estimated_minimum_minutes == 1


def test_15m_full_day_5k_symbols_fits_25_batches_of_200():
    r = plan(
        universe(5000), endpoint="minute_kline_batch",
        minute_period="15m", estimated_rows_per_symbol=16,
    )
    assert r.status == "REVIEW_ONLY"
    assert r.planned_requests == 25
    assert r.max_symbols_per_request == 200
    assert r.recommended_requests_per_minute == 45


def test_single_minute_240_rows_row_ceiling_beats_200_symbol_limit():
    r = plan(
        universe(5000), endpoint="minute_kline_batch",
        minute_period="1m", estimated_rows_per_symbol=240,
    )
    assert r.status == "REVIEW_ONLY"
    assert r.max_symbols_per_request == 41
    assert r.planned_requests == 122
    assert r.estimated_minimum_minutes == 3
    assert r.provider_requests == 0


def test_ws_symbols_are_200_per_connection_not_connection_entitlement():
    for number, count in ((1,1),(200,1),(201,2),(5000,25)):
        r = plan(universe(number), endpoint="websocket_quotes")
        assert r.status == "UNKNOWN"
        assert r.reason == "WEBSOCKET_CONNECTION_AND_ACCOUNT_QUOTA_UNVERIFIED"
        assert r.proposed_ws_connections == count
        assert r.provider_requests == 0
        assert r.source_arbiter_admission == "BLOCKED"


@pytest.mark.parametrize(
    "symbols,endpoint,kwargs,reason",
    [
        ((), "realtime_quote_batch", {}, "SYMBOL_UNIVERSE_INVALID"),
        (("159611.SZ", "159611.SZ"), "realtime_quote_batch", {}, "SYMBOL_UNIVERSE_INVALID"),
        (("bad",), "realtime_quote_batch", {}, "SYMBOL_UNIVERSE_INVALID"),
        (["159611.SZ"], "realtime_quote_batch", {}, "SYMBOL_UNIVERSE_INVALID"),
        (("159611.SZ",), "margin", {}, "ENDPOINT_CLASS_UNSUPPORTED"),
        (("159611.SZ",), "minute_kline_batch", {"minute_history_days":366}, "MINUTE_ENTITLEMENT_WINDOW_INVALID"),
        (("159611.SZ",), "minute_kline_batch", {"minute_period":"1d"}, "MINUTE_ENTITLEMENT_WINDOW_INVALID"),
        (("159611.SZ",), "minute_kline_batch", {"estimated_rows_per_symbol":0}, "ROWS_PER_SYMBOL_UNVERIFIED_OR_TOO_LARGE"),
        (("159611.SZ",), "minute_kline_batch", {"estimated_rows_per_symbol":10001}, "ROWS_PER_SYMBOL_UNVERIFIED_OR_TOO_LARGE"),
        (("159611.SZ","512730.SH"), "minute_kline_single", {}, "SINGLE_MINUTE_ENDPOINT_REQUIRES_ONE_SYMBOL"),
        (("159611.SZ",), "realtime_quote_batch", {"headroom_percent":True}, "HEADROOM_PERCENT_INVALID"),
        (("159611.SZ",), "realtime_quote_batch", {"headroom_percent":51}, "HEADROOM_PERCENT_INVALID"),
        (("159611.SZ",), "daily_kline_batch", {"minute_period":"1m"}, "MINUTE_SETTINGS_NOT_APPLICABLE"),
    ],
)
def test_fail_closed_inputs_and_unverified_history(symbols, endpoint, kwargs, reason):
    result = plan(symbols, endpoint=endpoint, **kwargs)
    assert result.status != "REVIEW_ONLY"
    assert result.reason == reason
    assert result.provider_requests == 0
    assert result.radar_admission == "BLOCKED"


def test_plan_does_not_reserve_any_real_account_quota():
    r = plan(("159611.SZ","512730.SH"), endpoint="minute_kline_batch")
    assert r.advertised_source == "USER_EXPERT_199_CNY_MONTH_SCREENSHOT_20261011_NOT_ACCOUNT_VERIFIED"
    assert r.provider_requests == r.quota_reserved == 0
    assert "SHARED" in r.reason

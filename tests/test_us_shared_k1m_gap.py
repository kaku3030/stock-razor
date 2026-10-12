"""Synthetic correlated OpenD minute-hole triage; never an order or provider test."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from data_provider.market_data_adapter import Bar
from src.services.live_feed.us_shared_k1m_gap import (
    audit_shared_us_k1m_interior_gaps,
)


ET = ZoneInfo("America/New_York")
SYMBOLS = ("US.AMD", "US.NVDA", "US.TSLA", "US.AAPL", "US.QQQ",
           "US.GLDM", "US.LITE", "US.AAOI", "US.CIEN")
START = datetime(2026, 10, 12, 9, 30, tzinfo=ET)
AS_OF = datetime(2026, 10, 12, 11, 2, tzinfo=ET)


def _bar(symbol, minute):
    end = minute + timedelta(minutes=1)
    return Bar(
        symbol=symbol, market="us", asset_type="stock", timeframe="1m",
        bar_start=minute, bar_end=end,
        open=100, high=100, low=100, close=100, volume=10, amount=1000,
        provider="futu", feed="opend", source_timestamp=end,
        received_at=end + timedelta(seconds=1), session="regular",
        is_closed=True, is_complete=True,
    )


def _grid():
    return {
        symbol: [
            _bar(symbol, START + timedelta(minutes=i))
            for i in range(91)
        ]
        for symbol in SYMBOLS
    }


def _audit(bars, *, as_of=AS_OF):
    return audit_shared_us_k1m_interior_gaps(
        bars, symbols=SYMBOLS, as_of=as_of,
    )


def _assert_never_promotes(out):
    assert out.research_only
    assert out.root_cause_proven is False
    assert out.provider_live_qualified is False
    assert out.bar_closure_promotion_authorized is False
    assert out.radar_admission == out.source_arbiter_admission == "BLOCKED"
    assert out.paper_auto_ready is False
    assert out.live_trade == out.trade_execution == "NO"


def test_nine_symbols_share_one_provider_time_hole_without_making_up_bar():
    actual = _grid()
    hole = START + timedelta(minutes=88)  # 2026-10-12 10:58 EDT
    assert hole.astimezone(timezone.utc).isoformat() == "2026-10-12T14:58:00+00:00"
    for symbol in SYMBOLS:
        actual[symbol] = [bar for bar in actual[symbol] if bar.bar_start != hole]
    outcome = _audit(actual)
    assert outcome.status == "SHARED_GAP_OBSERVED"
    assert outcome.symbol_count == 9
    assert outcome.common_observed_minutes == 89
    assert outcome.missing_in_all_symbols_utc == ("2026-10-12T14:58:00+00:00",)
    assert outcome.reason == "CORRELATED_INTERIOR_K1M_GAP"
    _assert_never_promotes(outcome)
    assert all(
        len(actual[symbol]) == 90 for symbol in SYMBOLS
    )  # Pure audit cannot fill even one original bar.


def test_one_symbol_gap_does_not_claim_correlated_upstream_failure():
    actual = _grid()
    actual[SYMBOLS[0]].pop(88)
    outcome = _audit(actual)
    assert outcome.status == "NO_SHARED_GAP_OBSERVED"
    assert outcome.missing_in_all_symbols_utc == ()
    _assert_never_promotes(outcome)


def test_missing_latest_bar_is_unobserved_trailing_boundary_not_shared_hole():
    actual = _grid()
    for symbol in SYMBOLS:
        actual[symbol].pop()
    outcome = _audit(actual)
    assert outcome.status == "NO_SHARED_GAP_OBSERVED"
    assert not outcome.missing_in_all_symbols_utc
    _assert_never_promotes(outcome)


def test_incomplete_or_wrong_source_bar_blocks_instead_of_causing_false_green():
    for changed in (
        {"is_closed": False, "is_complete": False},
        {"provider": "other"},
        {"feed": "not-opend"},
        {"timeframe": "15m"},
        {"source_timestamp": START},
        {"quality_flags": ("MISSING_BAR",)},
    ):
        actual = _grid()
        actual[SYMBOLS[0]][5] = replace(actual[SYMBOLS[0]][5], **changed)
        outcome = _audit(actual)
        assert outcome.status == "UNKNOWN"
        assert outcome.reason == "CANONICAL_PROVENANCE_OR_CLOSURE_INVALID"
        _assert_never_promotes(outcome)


def test_duplicate_minute_and_missing_symbol_cannot_be_a_confirmed_shared_gap():
    actual = _grid()
    actual[SYMBOLS[0]].append(actual[SYMBOLS[0]][5])
    out = _audit(actual)
    assert out.status == "UNKNOWN"
    assert out.reason == "DUPLICATE_MINUTE_EVIDENCE"
    _assert_never_promotes(out)

    actual = _grid()
    actual.pop(SYMBOLS[2])
    out = _audit(actual)
    assert out.status == "UNKNOWN"
    assert out.reason == "CANONICAL_ROWS_UNAVAILABLE"
    _assert_never_promotes(out)


def test_time_and_symbol_validation_fail_closed():
    actual = _grid()
    for as_of in (datetime(2026, 10, 12, 11, 2), None):
        out = _audit(actual, as_of=as_of)
        assert out.status == "UNKNOWN"
        assert out.reason == "OBSERVATION_TIME_UNVERIFIED"
        _assert_never_promotes(out)

    out = audit_shared_us_k1m_interior_gaps(
        actual, symbols=("US.AMD", "US.AMD"), as_of=AS_OF,
    )
    assert out.status == "UNKNOWN"
    assert out.reason == "EXPECTED_SYMBOL_SET_INVALID"
    _assert_never_promotes(out)

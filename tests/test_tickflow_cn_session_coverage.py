"""Synthetic minute coverage, no API/SDK, no paid requests or market data."""
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

from data_provider.tickflow_history_contract import HistoryRow
from data_provider.tickflow_cn_session_coverage import review_a_share_minute_session

DAY = date(2026, 10, 9)  # Friday, test fixture; not a live calendar claim.
CST = timezone(timedelta(hours=8))
SYMS = ("159611.SZ", "512730.SH")


def sample(symbols=SYMS, minutes=15, semantic="BAR_END"):
    offset = minutes if semantic == "BAR_END" else 0
    rows = []
    for symbol in symbols:
        for opening in (time(9, 30), time(13, 0)):
            start = datetime.combine(DAY, opening, tzinfo=CST)
            for elapsed in range(0, 120, minutes):
                ts = start + timedelta(minutes=elapsed + offset)
                rows.append(HistoryRow(symbol, ts.astimezone(timezone.utc), "TICKFLOW"))
    return tuple(rows)


def review(rows=None, *, symbols=SYMS, minutes="15m", semantic="BAR_END", **overrides):
    kwargs = dict(
        expected_symbols=symbols,
        trading_day=DAY,
        timeframe=minutes,
        timestamp_semantic=semantic,
        trading_session_confirmed=True,
        timestamp_semantic_verified=True,
    )
    kwargs.update(overrides)
    return review_a_share_minute_session(
        sample(symbols, int(minutes.rstrip("m")), semantic) if rows is None else rows,
        **kwargs,
    )


def test_complete_sessions_1m_5m_15m_30m_60m_all_review_only():
    for minutes, per_symbol in (
        (1, 240), (5, 48), (15, 16), (30, 8), (60, 4)
    ):
        for semantic in ("BAR_END", "BAR_START"):
            result = review(
                sample(SYMS, minutes, semantic),
                minutes=f"{minutes}m", semantic=semantic,
            )
            assert result.status == "REVIEW_ONLY"
            assert result.expected_bars == len(SYMS) * per_symbol
            assert result.missing_bars == result.unexpected_bars == 0
            assert result.duplicate_bars == 0
            assert result.provider_calls == result.provider_quota_reserved == 0
            assert result.radar_admission == "BLOCKED"
            assert result.source_arbiter_admission == "BLOCKED"
            assert not result.paper_auto_ready and not result.live_trade


def test_missing_one_bar_and_lunch_break_extra_bar_are_blocked():
    rows = sample()
    missing = review(rows[:-1])
    assert missing.status == "BLOCKED"
    assert missing.missing_bars == 1
    at_lunch = HistoryRow("159611.SZ", datetime.combine(
        DAY, time(12, 15), tzinfo=CST
    ), "TICKFLOW")
    invalid = review((*rows, at_lunch))
    assert invalid.status == "BLOCKED"
    assert invalid.unexpected_bars == 1


def test_duplicate_bar_and_wrong_source_fail_closed():
    rows = sample()
    dup = review((*rows, rows[0]))
    assert dup.status == "BLOCKED"
    assert dup.duplicate_bars == 1
    wrong = review((replace(rows[0], source="TENCENT"), *rows[1:]))
    assert wrong.status == "BLOCKED"
    assert wrong.reason == "INVALID_ROW_OR_SOURCE"


def test_semantics_calendar_and_session_confirmations_are_not_inferred():
    rows = sample()
    assert review(
        rows, timestamp_semantic_verified=False
    ).reason == "TIMESTAMP_SEMANTIC_NOT_VERIFIED"
    assert review(
        rows, trading_session_confirmed=False
    ).reason == "TRADING_SESSION_CONFIRMATION_MISSING"
    assert review(rows, semantic="UNKNOWN").status == "UNKNOWN"
    assert review(
        rows, trading_day=date(2026, 10, 10)
    ).status == "UNKNOWN"


def test_naive_timestamp_non_etf_symbol_and_unhashable_keys_fail_closed():
    rows = sample()
    naive = review((replace(rows[0], timestamp=rows[0].timestamp.replace(
        tzinfo=None
    )), *rows[1:]))
    assert naive.status == "BLOCKED"
    assert review(rows, symbols=("159611.SZ", ["BAD"])).status == "BLOCKED"
    assert review(rows, symbols=("159611.SZ", "159611.SZ")).status == "BLOCKED"
    assert review(rows, minutes=[]).status == "BLOCKED"


def test_alternate_semantic_cannot_mislabel_end_bars_as_start_bars():
    end_rows = sample()
    result = review(end_rows, semantic="BAR_START")
    assert result.status == "BLOCKED"
    assert result.missing_bars > 0 and result.unexpected_bars > 0


def test_large_or_malformed_row_collections_do_not_succeed():
    rows = sample(SYMS, 1)
    assert review(rows * 3, minutes="1m").status == "BLOCKED"
    assert review(None, trading_session_confirmed=False).status == "UNKNOWN"
    assert review(("bogus",), minutes="15m").status == "BLOCKED"

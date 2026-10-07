from datetime import date, datetime, timedelta

from src.services.live_feed.futu_k1m_history_qualification import (
    FUTU_US_K1M_REGULAR_SESSION_ROWS,
    qualify_futu_us_k1m_history,
)


SESSION_DATE = date(2026, 10, 6)
SYMBOL = "US.AMD"


def _rows():
    first = datetime(2026, 10, 6, 9, 31)
    rows = []
    for index in range(FUTU_US_K1M_REGULAR_SESSION_ROWS):
        stamp = first + timedelta(minutes=index)
        close = 100.0 + index / 100
        rows.append(
            {
                "code": SYMBOL,
                "time_key": stamp.strftime("%Y-%m-%d %H:%M:%S"),
                "open": close - 0.05,
                "high": close + 0.10,
                "low": close - 0.10,
                "close": close,
                "volume": 1000 + index,
                "turnover": (1000 + index) * close,
            }
        )
    return rows


def test_completed_regular_session_is_research_seed_eligible_only():
    result = qualify_futu_us_k1m_history(
        _rows(),
        expected_symbol=SYMBOL,
        expected_session_date=SESSION_DATE,
    )

    assert result.status == "PASS"
    assert result.research_cache_seed_eligible is True
    assert result.row_count == 390
    assert result.first_time_key == "2026-10-06 09:31:00"
    assert result.last_time_key == "2026-10-06 16:00:00"
    assert result.timestamp_semantics == "INTERVAL_END_PROVEN_US_K1M"
    assert result.historical_query is True
    assert result.realtime_currentness_proven is False
    assert result.bar_closure_promotion_authorized is False
    assert result.radar_admission == "BLOCKED"
    assert result.live_trade is False


def test_missing_minute_blocks_warm_start_qualification():
    rows = _rows()
    del rows[120]

    result = qualify_futu_us_k1m_history(rows, expected_symbol=SYMBOL)

    assert result.status == "BLOCKED"
    assert result.research_cache_seed_eligible is False
    assert "REGULAR_SESSION_GRID_INCOMPLETE" in result.reasons


def test_duplicate_minute_blocks_warm_start_qualification():
    rows = _rows()
    rows.insert(50, dict(rows[49]))

    result = qualify_futu_us_k1m_history(rows, expected_symbol=SYMBOL)

    assert result.status == "BLOCKED"
    assert "DUPLICATE_TIME_KEY" in result.reasons
    assert "REGULAR_SESSION_GRID_INCOMPLETE" in result.reasons


def test_out_of_order_rows_block_warm_start_qualification():
    rows = _rows()
    rows[10], rows[11] = rows[11], rows[10]

    result = qualify_futu_us_k1m_history(rows, expected_symbol=SYMBOL)

    assert result.status == "BLOCKED"
    assert "OUT_OF_ORDER_TIME_KEY" in result.reasons
    assert "REGULAR_SESSION_GRID_INCOMPLETE" in result.reasons


def test_symbol_mismatch_is_fail_closed():
    rows = _rows()
    rows[0]["code"] = "US.NVDA"

    result = qualify_futu_us_k1m_history(rows, expected_symbol=SYMBOL)

    assert result.status == "BLOCKED"
    assert "SYMBOL_MISMATCH" in result.reasons


def test_invalid_ohlc_is_fail_closed():
    rows = _rows()
    rows[25]["high"] = rows[25]["low"] - 1

    result = qualify_futu_us_k1m_history(rows, expected_symbol=SYMBOL)

    assert result.status == "BLOCKED"
    assert "INVALID_OHLC" in result.reasons


def test_negative_volume_and_turnover_are_fail_closed():
    rows = _rows()
    rows[30]["volume"] = -1
    rows[31]["turnover"] = -1

    result = qualify_futu_us_k1m_history(rows, expected_symbol=SYMBOL)

    assert result.status == "BLOCKED"
    assert "NEGATIVE_VOLUME" in result.reasons
    assert "NEGATIVE_TURNOVER" in result.reasons


def test_wrong_completed_session_date_is_fail_closed():
    result = qualify_futu_us_k1m_history(
        _rows(),
        expected_symbol=SYMBOL,
        expected_session_date=date(2026, 10, 5),
    )

    assert result.status == "BLOCKED"
    assert "SESSION_DATE_MISMATCH" in result.reasons
    assert "REGULAR_SESSION_GRID_INCOMPLETE" in result.reasons


def test_serialized_contract_cannot_imply_promotion():
    payload = qualify_futu_us_k1m_history(
        _rows(),
        expected_symbol=SYMBOL,
        expected_session_date=SESSION_DATE,
    ).to_dict()

    assert payload["status"] == "PASS"
    assert payload["research_cache_seed_eligible"] is True
    assert payload["realtime_currentness_proven"] is False
    assert payload["bar_closure_promotion_authorized"] is False
    assert payload["radar_admission"] == "BLOCKED"
    assert payload["live_trade"] is False

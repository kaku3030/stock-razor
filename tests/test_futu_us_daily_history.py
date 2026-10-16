from datetime import datetime, timedelta, timezone

from src.services.live_feed.futu_us_daily_history import (
    build_futu_us_daily_history,
    daily_history_refresh_due,
    normalize_futu_us_daily_history_rows,
)


NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def _rows(symbol="US.AMD", count=140, include_current=False):
    start = datetime(2026, 3, 1)
    rows = []
    day = start
    while len(rows) < count:
        if day.weekday() < 5:
            price = 100 + len(rows) * 0.5
            rows.append(
                {
                    "code": symbol,
                    "time_key": day.strftime("%Y-%m-%d 00:00:00"),
                    "open": price,
                    "high": price + 2,
                    "low": price - 2,
                    "close": price + 1,
                    "volume": 1000 + len(rows),
                    "turnover": 100000 + len(rows),
                }
            )
        day += timedelta(days=1)
    if include_current:
        rows.append(
            {
                "code": symbol,
                "time_key": "2026-10-07 00:00:00",
                "open": 200,
                "high": 205,
                "low": 198,
                "close": 203,
                "volume": 5000,
                "turnover": 1000000,
            }
        )
    return rows


def test_normalizer_selects_last_120_completed_prior_sessions():
    result = normalize_futu_us_daily_history_rows(
        _rows(count=140),
        expected_symbol="US.AMD",
        observed_at_utc=NOW,
        required_rows=120,
    )

    assert result["status"] == "PASS"
    assert result["row_count"] == 120
    assert len(result["rows"]) == 120
    assert result["rows"][0]["date"] < result["rows"][-1]["date"]
    assert result["completed_prior_session_only"] is True
    assert result["historical_query"] is True
    assert result["currentness_proven"] is False
    assert result["bar_closure_promotion_authorized"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_current_market_date_is_always_excluded():
    result = normalize_futu_us_daily_history_rows(
        _rows(count=140, include_current=True),
        expected_symbol="US.AMD",
        observed_at_utc=NOW,
        required_rows=120,
    )

    assert result["status"] == "PASS"
    assert result["latest_date"] < "2026-10-07"
    assert all(row["date"] != "2026-10-07" for row in result["rows"])


def test_insufficient_history_blocks_without_partial_pass():
    result = normalize_futu_us_daily_history_rows(
        _rows(count=80),
        expected_symbol="US.AMD",
        observed_at_utc=NOW,
        required_rows=120,
    )

    assert result["status"] == "BLOCKED"
    assert result["rows"] == []
    assert result["reasons"] == ["INSUFFICIENT_COMPLETED_DAILY_ROWS"]


def test_invalid_ohlc_blocks():
    rows = _rows(count=140)
    rows[10] = {**rows[10], "high": rows[10]["low"] - 1}

    result = normalize_futu_us_daily_history_rows(
        rows,
        expected_symbol="US.AMD",
        observed_at_utc=NOW,
        required_rows=120,
    )

    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["INVALID_OHLC"]


def test_build_daily_history_isolates_symbol_query_failure():
    good = _rows(symbol="US.AMD", count=140)

    def fetch(symbol, start, end):
        if symbol == "US.NVDA":
            raise RuntimeError("provider")
        return good

    result = build_futu_us_daily_history(
        ["US.AMD", "US.NVDA"],
        fetch_rows=fetch,
        repo_sha="a" * 40,
        runtime_instance_id="runtime-1",
        observed_at_utc=NOW,
    )

    assert result["status"] == "PARTIAL"
    assert result["symbols"]["US.AMD"]["status"] == "PASS"
    assert result["symbols"]["US.NVDA"]["status"] == "BLOCKED"
    assert result["symbols"]["US.NVDA"]["reasons"] == [
        "DAILY_QUERY_EXCEPTION:RuntimeError"
    ]
    assert result["same_opend_context_required"] is True
    assert result["research_only"] is True
    assert result["can_confirm_signal"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_daily_refresh_waits_until_one_am_new_york_time():
    before_window = datetime(2026, 10, 16, 4, 59, tzinfo=timezone.utc)
    at_window = datetime(2026, 10, 16, 5, 0, tzinfo=timezone.utc)

    assert daily_history_refresh_due(before_window, None) is False
    assert daily_history_refresh_due(at_window, None) is True


def test_daily_refresh_is_limited_to_once_per_new_york_date():
    first_attempt = datetime(2026, 10, 16, 5, 5, tzinfo=timezone.utc)
    later_same_day = datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc)
    next_weekday = datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc)

    assert daily_history_refresh_due(later_same_day, first_attempt) is False
    assert daily_history_refresh_due(next_weekday, first_attempt) is True


def test_daily_refresh_skips_weekends():
    saturday = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)

    assert daily_history_refresh_due(saturday, None) is False


def test_daily_refresh_rejects_naive_timestamps():
    import pytest

    with pytest.raises(ValueError, match="timezone-aware"):
        daily_history_refresh_due(datetime(2026, 10, 16, 5, 0), None)

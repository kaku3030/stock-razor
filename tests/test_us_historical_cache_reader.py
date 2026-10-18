import json

from data_provider.us_historical_cache_reader import read_us_historical_bars


def _cache(path):
    path.write_text(json.dumps({
        "schema": "stock_razor_us_historical_cache_v1",
        "source": "futu/opend",
        "source_sha256": "abc",
        "symbols": {"US.TSLA": {"1h": [
            {"timestamp": "2026-08-03T10:30:00", "close": 300},
            {"timestamp": "2026-08-04T10:30:00", "close": 305},
        ]}},
    }), encoding="utf-8")


def test_missing_cache_is_explicit_and_provider_free(tmp_path):
    result = read_us_historical_bars("US.TSLA", start_date="2026-08-03", end_date="2026-08-04", path=str(tmp_path / "missing.json"))
    assert result["status"] == "CACHE_MISSING"
    assert result["error"] == "HISTORICAL_CACHE_MISSING"
    assert result["provider_requests"] == 0


def test_date_filter_and_cursor_are_bounded(tmp_path):
    path = tmp_path / "history.json"
    _cache(path)
    first = read_us_historical_bars("US.TSLA", start_date="2026-08-03", end_date="2026-08-04", timeframe="1h", limit=1, path=str(path))
    second = read_us_historical_bars("US.TSLA", start_date="2026-08-03", end_date="2026-08-04", timeframe="1h", limit=1, cursor=1, path=str(path))
    assert first["status"] == second["status"] == "PASS_HISTORICAL_ONLY"
    assert first["bars"][0]["close"] == 300
    assert second["bars"][0]["close"] == 305
    assert first["next_cursor"] == 1
    assert second["next_cursor"] is None
    assert first["provider_requests"] == 0


def test_invalid_range_and_cache_schema_fail_closed(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{}", encoding="utf-8")
    invalid = read_us_historical_bars("US.TSLA", start_date="2026-08-04", end_date="2026-08-03", path=str(path))
    bad_cache = read_us_historical_bars("US.TSLA", start_date="2026-08-03", end_date="2026-08-04", path=str(path))
    assert invalid["error"] == "INVALID_DATE_RANGE"
    assert bad_cache["error"] == "HISTORICAL_CACHE_SCHEMA_INVALID"

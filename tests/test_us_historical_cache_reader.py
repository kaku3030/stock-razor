import hashlib
import json

from data_provider.us_historical_cache_reader import read_us_historical_bars


def _cache(path, rows=None):
    metadata = {"provider": "futu/opend", "capture_id": "capture-1"}
    payload = {
        "schema": "stock_razor_us_historical_cache_v1",
        "cache_version": "v1:2026-08-04T20:00:00Z",
        "source": "futu/opend",
        "source_metadata": metadata,
        "source_sha256": hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "calendar": {
            "timezone": "America/New_York",
            "rth_start": "09:30",
            "rth_end": "16:00",
            "trading_dates": ["2026-08-03", "2026-08-04"],
        },
        "symbols": {"US.TSLA": {"1h": rows or [
            {"session_date": "2026-08-03", "timestamp": "2026-08-03T10:30:00-04:00", "session": "RTH", "closed": True, "open": 300, "high": 302, "low": 299, "close": 301, "volume": 1000},
            {"session_date": "2026-08-04", "timestamp": "2026-08-04T10:30:00-04:00", "session": "RTH", "closed": True, "open": 301, "high": 306, "low": 300, "close": 305, "volume": 1200},
        ]}},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read(path, **kwargs):
    return read_us_historical_bars("US.TSLA", start_date="2026-08-03", end_date="2026-08-04", path=str(path), **kwargs)


def test_missing_cache_is_explicit_and_provider_free(tmp_path):
    result = _read(tmp_path / "missing.json")
    assert result["status"] == "CACHE_MISSING"
    assert result["error"] == "HISTORICAL_CACHE_MISSING"
    assert result["provider_requests"] == 0


def test_rows_are_normalized_and_cursor_is_bound_to_snapshot(tmp_path):
    path = tmp_path / "history.json"
    _cache(path)
    first = _read(path, limit=1)
    second = _read(path, limit=1, cursor=first["next_cursor"])
    assert first["status"] == second["status"] == "PASS_HISTORICAL_ONLY"
    assert first["bars"][0]["timestamp"] == "2026-08-03T14:30:00Z"
    assert second["bars"][0]["close"] == 305
    assert first["next_cursor"] != first["cache_snapshot_sha256"] + ":1"
    path.write_text(path.read_text(encoding="utf-8").replace('"close": 305', '"close": 304'), encoding="utf-8")
    changed = _read(path, limit=1, cursor=first["next_cursor"])
    assert changed["error"] == "HISTORICAL_CACHE_SNAPSHOT_CHANGED"


def test_cursor_rejects_a_different_query_on_the_same_snapshot(tmp_path):
    path = tmp_path / "history.json"
    _cache(path)
    first = _read(path, limit=1)
    changed_query = read_us_historical_bars(
        "US.TSLA", start_date="2026-08-04", end_date="2026-08-04",
        timeframe="1h", limit=1, cursor=first["next_cursor"], path=str(path),
    )
    assert changed_query["error"] == "HISTORICAL_CURSOR_QUERY_MISMATCH"


def test_missing_fields_and_source_hash_fail_closed(tmp_path):
    path = tmp_path / "invalid.json"
    _cache(path, rows=[{"session_date": "2026-08-03", "timestamp": "2026-08-03T10:30:00-04:00", "session": "RTH", "closed": True, "close": 300}])
    assert _read(path)["error"] == "HISTORICAL_CACHE_BAR_INVALID"
    _cache(path)
    path.write_text(path.read_text(encoding="utf-8").replace('"source_sha256": "', '"source_sha256": "0'), encoding="utf-8")
    assert _read(path)["error"] == "HISTORICAL_CACHE_METADATA_INVALID"


def test_nonfinite_price_volume_and_price_bounds_fail_closed(tmp_path):
    path = tmp_path / "invalid.json"
    rows = [{"session_date": "2026-08-03", "timestamp": "2026-08-03T10:30:00-04:00", "session": "RTH", "closed": True, "open": float("nan"), "high": 302, "low": 299, "close": 301, "volume": 1000}]
    _cache(path, rows=rows)
    assert _read(path)["error"] == "HISTORICAL_CACHE_BAR_INVALID"
    rows[0]["open"] = 300
    rows[0]["low"] = 302
    _cache(path, rows=rows)
    assert _read(path)["error"] == "HISTORICAL_CACHE_BAR_INVALID"
    rows[0]["low"] = 299
    rows[0]["volume"] = -1
    _cache(path, rows=rows)
    assert _read(path)["error"] == "HISTORICAL_CACHE_BAR_INVALID"


def test_timezone_rth_calendar_closed_and_order_fail_closed(tmp_path):
    path = tmp_path / "invalid.json"
    rows = [{"session_date": "2026-08-03", "timestamp": "2026-08-03T10:30:00", "session": "RTH", "closed": True, "open": 300, "high": 302, "low": 299, "close": 301, "volume": 1000}]
    _cache(path, rows=rows)
    assert _read(path)["error"] == "HISTORICAL_CACHE_BAR_INVALID"
    rows[0]["timestamp"] = "2026-08-03T08:30:00-04:00"
    _cache(path, rows=rows)
    assert _read(path)["error"] == "HISTORICAL_CACHE_BAR_INVALID"
    rows[0]["timestamp"] = "2026-08-03T10:30:00-04:00"
    rows[0]["closed"] = False
    _cache(path, rows=rows)
    assert _read(path)["error"] == "HISTORICAL_CACHE_BAR_INVALID"
    rows[0]["closed"] = True
    rows.append(dict(rows[0]))
    _cache(path, rows=rows)
    assert _read(path)["error"] == "HISTORICAL_CACHE_BAR_INVALID"


def test_invalid_range_and_cache_schema_fail_closed(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{}", encoding="utf-8")
    invalid = read_us_historical_bars("US.TSLA", start_date="2026-08-04", end_date="2026-08-03", path=str(path))
    bad_cache = _read(path)
    assert invalid["error"] == "INVALID_DATE_RANGE"
    assert bad_cache["error"] == "HISTORICAL_CACHE_SCHEMA_INVALID"

"""Read-only US D1 compatibility path is historical-only and fail-closed."""
from datetime import datetime, timedelta, timezone
import json

from data_provider.us_daily_research_reader import read_us_completed_daily_research

NOW = datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def _health(**overrides):
    return {
        "ok": True, "status": "HEALTHY",
        "canonical_snapshot_status": "PASS",
        "delivery_mode": "REALTIME",
        "radar_admission": "BLOCKED", "live_trade": False,
        "repo_sha": SHA, "runtime_instance_id": "open-runtime",
        **overrides,
    }


def _payload():
    start = (NOW - timedelta(days=135)).date()
    rows = []
    for index in range(120):
        day = start + timedelta(days=index)
        rows.append({
            "date": day.isoformat(),
            "open": 100.0, "high": 103.0, "low": 99.0, "close": 101.0,
            "volume": 10_000.0, "amount": 1_005_000.0,
            "provider": "futu", "feed": "opend",
            "quality_flags": ["HISTORICAL_QUERY"],
        })
    return {
        "schema": "stock_razor_futu_us_daily_history_v1",
        "repo_sha": SHA, "runtime_instance_id": "open-runtime",
        "emitted_at_utc": (NOW - timedelta(minutes=10)).isoformat(),
        "status": "PASS", "provider": "futu", "feed": "opend",
        "same_opend_context_required": True,
        "historical_query": True, "research_only": True,
        "currentness_proven": False, "bar_closure_promotion_authorized": False,
        "can_confirm_signal": False, "radar_admission": "BLOCKED",
        "live_trade": False,
        "symbols": {
            "US.NVDA": {
                "status": "PASS", "symbol": "US.NVDA",
                "completed_prior_session_only": True,
                "historical_query": True, "currentness_proven": False,
                "bar_closure_promotion_authorized": False,
                "radar_admission": "BLOCKED", "live_trade": False,
                "rows": rows,
            }
        },
    }


def _write(tmp_path, body):
    p = tmp_path / "daily-history.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return str(p)


def _read(tmp_path, body, *, health=None, limit=5):
    return read_us_completed_daily_research(
        "NVDA", limit=limit, path=_write(tmp_path, body),
        now_utc=NOW, livefeed_health=_health() if health is None else health,
    )


def test_prior_session_native_daily_cache_reads_without_provider_io(tmp_path):
    result = _read(tmp_path, _payload(), limit=3)
    assert result["status"] == "PASS_HISTORICAL_ONLY"
    assert result["ok"] is True
    assert result["bar_count"] == 3
    assert result["total_bar_count"] == 120
    assert result["bars"][-1]["date"] < "2026-10-14"
    assert result["bars"][-1]["close"] == 101.0
    assert result["bars"][-1]["quality_flags"] == ["HISTORICAL_QUERY"]
    assert result["provider_finality"] == "NOT_VERIFIED"
    assert result["current_session_daily_bar"] == "NOT_AVAILABLE"
    assert result["provider_requests"] == 0
    assert result["radar_admission"] == "BLOCKED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["paper_auto_ready"] is False
    assert result["live_trade"] is False
    assert result["can_confirm_signal"] is False


def test_no_daily_cache_and_unknown_livefeed_fail_closed(tmp_path):
    missing = read_us_completed_daily_research(
        "NVDA", path=str(tmp_path / "absent.json"),
        now_utc=NOW, livefeed_health=_health(),
    )
    unsafe = _read(tmp_path, _payload(), health=_health(status="STALE"))
    for item in (missing, unsafe):
        assert item["status"] == "BLOCKED"
        assert item["bars"] == []
        assert item["radar_admission"] == "BLOCKED"
        assert item["provider_finality"] == "NOT_VERIFIED"


def test_daily_cache_sha_and_runtime_must_match_livefeed(tmp_path):
    body = _payload()
    body["repo_sha"] = "b" * 40
    assert _read(tmp_path, body)["reason"] == "DAILY_LIVEFEED_LINEAGE_MISMATCH"
    body = _payload()
    body["runtime_instance_id"] = "other"
    assert _read(tmp_path, body)["reason"] == "DAILY_LIVEFEED_LINEAGE_MISMATCH"


def test_daily_cache_current_session_d1_is_never_assumed_closed(tmp_path):
    body = _payload()
    body["symbols"]["US.NVDA"]["rows"][-1]["date"] = "2026-10-14"
    assert _read(tmp_path, body)["reason"] == "DAILY_DATE_NOT_PRIOR_OR_ORDERED"


def test_nonfinite_and_malformed_ohlcv_are_rejected(tmp_path):
    for key, value in (("high", 1.0), ("low", 102.0),
                       ("volume", -1), ("close", float("nan"))):
        body = _payload()
        body["symbols"]["US.NVDA"]["rows"][-1][key] = value
        result = _read(tmp_path, body)
        assert result["status"] == "BLOCKED"
        assert result["bars"] == []
        assert result["reason"] in {"DAILY_OHLCV_OR_ORIGIN_INVALID", "DAILY_ROW_INVALID"}


def test_fail_closed_on_bad_source_flags_future_or_duplicate_dates(tmp_path):
    body = _payload()
    body["radar_admission"] = "ADMITTED"
    assert _read(tmp_path, body)["reason"] == "DAILY_SAFETY_CONTRACT_VIOLATION"

    body = _payload()
    rows = body["symbols"]["US.NVDA"]["rows"]
    rows[-1]["date"] = rows[-2]["date"]
    assert _read(tmp_path, body)["reason"] == "DAILY_DATE_NOT_PRIOR_OR_ORDERED"

    body = _payload()
    body["emitted_at_utc"] = (NOW - timedelta(days=5)).isoformat()
    assert _read(tmp_path, body)["reason"] == "DAILY_SOURCE_STALE"


def test_invalid_arguments_never_contact_provider(tmp_path):
    body = _payload()
    path = _write(tmp_path, body)
    assert read_us_completed_daily_research(
        "HK.00700", path=path, now_utc=NOW, livefeed_health=_health()
    )["reason"] == "INVALID_SYMBOL"
    assert read_us_completed_daily_research(
        "NVDA", limit=0, path=path, now_utc=NOW, livefeed_health=_health()
    )["reason"] == "INVALID_LIMIT"


def test_existing_mcp_market_bars_routes_daily_only():
    from pathlib import Path

    text = Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    assert "read_us_completed_daily_research(symbol, limit=limit)" in text
    assert 'if timeframe == "1d":' in text
    assert "return read_us_market_bars(symbol, timeframe=timeframe, limit=limit)" in text
    assert "get_market_bars" in text


def test_off_session_canonical_snapshot_stale_does_not_disable_historical_d1(tmp_path):
    # Real cloud can have a fresh connected heartbeat while no new canonical
    # intraday bars arrive during after-hours. K_DAY remains historical-only.
    evidence = _health(
        canonical_snapshot_status="STALE",
        delivery_mode="UNKNOWN",
        market_state_us="AFTER_HOURS_BEGIN",
    )
    result = _read(tmp_path, _payload(), health=evidence)
    assert result["status"] == "PASS_HISTORICAL_ONLY"
    assert result["bar_count"] == 5
    assert result["provider_requests"] == 0
    assert result["provider_finality"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"


def test_historical_d1_still_blocks_invalid_canonical_runtime(tmp_path):
    for bad_health in (
        _health(canonical_snapshot_status="INVALID"),
        _health(canonical_snapshot_status="UNAVAILABLE"),
        _health(delivery_mode="DELAYED"),
        _health(ok=False),
    ):
        result = _read(tmp_path, _payload(), health=bad_health)
        assert result["status"] == "BLOCKED"
        assert result["reason"] == "LIVEFEED_HEALTH_UNVERIFIED"
        assert result["bars"] == []

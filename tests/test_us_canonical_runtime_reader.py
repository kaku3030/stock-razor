from datetime import datetime, timedelta, timezone
import json
import os

from data_provider.us_canonical_runtime_reader import (
    read_us_livefeed_health,
    read_us_market_bars,
    read_us_market_snapshots,
)


NOW = datetime(2026, 10, 7, 4, 40, tzinfo=timezone.utc)
SHA = "a" * 40


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _bar(end, close):
    start = end - timedelta(minutes=1)
    return {
        "symbol": "US.AMD",
        "market": "us",
        "asset_type": "stock",
        "timeframe": "1m",
        "bar_start_utc": start.isoformat(),
        "bar_end_utc": end.isoformat(),
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 100,
        "amount": 1000,
        "vwap": 10,
        "provider": "futu",
        "feed": "opend",
        "source_timestamp_utc": end.isoformat(),
        "received_at_utc": end.isoformat(),
        "session": "regular",
        "is_closed": True,
        "is_complete": True,
        "fallback_from": None,
        "fallback_reason": None,
        "latency_ms": 0,
        "freshness_ms": 0,
        "quality_flags": [],
        "health": {
            "score": 90,
            "grade": "excellent",
            "signal_permission": "normal",
            "quality_flags": [],
        },
    }


def _snapshot(*, emitted_at=NOW - timedelta(seconds=10), safe=True):
    bars = [
        _bar(NOW - timedelta(minutes=2), 648.0),
        _bar(NOW - timedelta(minutes=1), 649.0),
    ]
    return {
        "schema": "stock_razor_canonical_market_snapshot_v1",
        "runtime_instance_id": "runtime-1",
        "repo_sha": SHA,
        "sequence": 7,
        "emitted_at_utc": emitted_at.isoformat(),
        "market_state_us": "MORNING",
        "cache_session_us": "regular",
        "delivery_mode": "REALTIME",
        "bar_closure": "PROVEN",
        "radar_admission": "BLOCKED" if safe else "ADMITTED",
        "live_trade": False,
        "symbols": {
            "US.AMD": {
                "symbol": "US.AMD",
                "provider": "futu",
                "feed": "opend",
                "health": {
                    "score": 90,
                    "grade": "excellent",
                    "signal_permission": "normal",
                    "quality_flags": [],
                },
                "timeframes": {
                    "1m": bars,
                    "5m": [],
                    "15m": [],
                    "1h": [],
                },
            }
        },
    }


def _heartbeat(*, emitted_at=NOW - timedelta(seconds=5), safe=True):
    return {
        "type": "us_opend_livefeed_heartbeat",
        "runtime_instance_id": "runtime-1",
        "repo_sha": SHA,
        "sequence": 50,
        "emitted_at_utc": emitted_at.isoformat(),
        "controller_lifecycle": "CONNECTED",
        "market_state_us": "MORNING",
        "cache_session_us": "regular",
        "delivery_mode": "REALTIME",
        "bar_closure": "PROVEN",
        "last_push_utc": (NOW - timedelta(seconds=3)).isoformat(),
        "event_count": 100,
        "accepted_event_count": 110,
        "quote_right_evidence": {"delivery_mode": "REALTIME"},
        "canonical_snapshot_export": {"status": "PASS"},
        "canonical_cache": {
            "US.AMD": {
                "bar_count": 2,
                "bar_count_5m": 0,
                "bar_count_15m": 0,
                "bar_count_1h": 0,
            }
        },
        "radar_admission": "BLOCKED" if safe else "ADMITTED",
        "live_trade": False,
    }


def test_livefeed_health_is_compact_and_fail_closed(tmp_path):
    status = _write(tmp_path / "heartbeat.json", _heartbeat())
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())

    result = read_us_livefeed_health(
        status,
        snapshot,
        now_utc=NOW,
    )

    assert result["ok"] is True
    assert result["status"] == "HEALTHY"
    assert result["delivery_mode"] == "REALTIME"
    assert result["bar_closure_proven"] is True
    assert result["cache_counts"]["US.AMD"]["1m"] == 2
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert result["read_latency_ms"] >= 0


def test_market_snapshots_accept_short_symbol_and_return_latest_only(tmp_path):
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())

    result = read_us_market_snapshots(["AMD"], path=snapshot, now_utc=NOW)

    assert result["ok"] is True
    assert result["status"] == "PASS"
    assert result["missing_symbols"] == []
    assert result["data_available"] is True
    assert result["symbols"]["US.AMD"]["counts"]["1m"] == 2
    assert result["symbols"]["US.AMD"]["latest"]["1m"]["close"] == 649.0
    assert result["symbols"]["US.AMD"]["latest"]["5m"] is None
    assert result["source_cache_hit"] is False
    assert result["read_latency_ms"] >= 0


def test_market_bars_are_bounded_and_keep_source_quality(tmp_path):
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())

    result = read_us_market_bars(
        "amd",
        timeframe="1m",
        limit=1,
        path=snapshot,
        now_utc=NOW,
    )

    assert result["ok"] is True
    assert result["bar_count"] == 1
    assert result["total_bar_count"] == 2
    assert result["bars"][0]["close"] == 649.0
    assert result["bars"][0]["health"]["signal_permission"] == "normal"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False
    assert result["read_latency_ms"] >= 0


def test_repeated_snapshot_reads_hit_cache_and_atomic_replace_invalidates(tmp_path):
    path = tmp_path / "snapshot.json"
    snapshot = _snapshot()
    _write(path, snapshot)

    first = read_us_market_bars("AMD", timeframe="1m", limit=1, path=str(path), now_utc=NOW)
    second = read_us_market_bars("AMD", timeframe="1m", limit=1, path=str(path), now_utc=NOW)

    assert first["source_cache_hit"] is False
    assert second["source_cache_hit"] is True
    assert second["bars"][0]["close"] == 649.0

    replacement = tmp_path / "snapshot.new.json"
    changed = _snapshot()
    changed["sequence"] = 8
    changed["symbols"]["US.AMD"]["timeframes"]["1m"][-1]["close"] = 650.0
    _write(replacement, changed)
    os.replace(replacement, path)

    third = read_us_market_bars("AMD", timeframe="1m", limit=1, path=str(path), now_utc=NOW)

    assert third["source_cache_hit"] is False
    assert third["sequence"] == 8
    assert third["bars"][0]["close"] == 650.0


def test_stale_snapshot_is_returned_as_stale_not_laundered(tmp_path):
    snapshot = _write(
        tmp_path / "snapshot.json",
        _snapshot(emitted_at=NOW - timedelta(minutes=10)),
    )

    result = read_us_market_bars(
        "AMD",
        timeframe="1m",
        limit=2,
        path=snapshot,
        now_utc=NOW,
    )

    assert result["ok"] is True
    assert result["status"] == "STALE"
    assert result["source_age_seconds"] == 600
    assert result["bar_count"] == 2


def test_snapshot_safety_contract_violation_blocks_reads(tmp_path):
    snapshot = _write(tmp_path / "snapshot.json", _snapshot(safe=False))

    snapshots = read_us_market_snapshots(["AMD"], path=snapshot, now_utc=NOW)
    bars = read_us_market_bars("AMD", path=snapshot, now_utc=NOW)

    for result in (snapshots, bars):
        assert result["ok"] is False
        assert result["status"] == "INVALID"
        assert result["error"] == "SAFETY_CONTRACT_VIOLATION"
        assert result["radar_admission"] == "BLOCKED"
        assert result["live_trade"] is False


def test_invalid_arguments_fail_closed_without_reading_provider(tmp_path):
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())

    bad_symbol = read_us_market_bars(
        "HK.00700",
        path=snapshot,
        now_utc=NOW,
    )
    bad_timeframe = read_us_market_bars(
        "AMD",
        timeframe="tick",
        path=snapshot,
        now_utc=NOW,
    )
    bad_limit = read_us_market_bars(
        "AMD",
        limit=1000,
        path=snapshot,
        now_utc=NOW,
    )

    assert bad_symbol["error"] == "INVALID_SYMBOL"
    assert bad_timeframe["error"] == "UNSUPPORTED_TIMEFRAME"
    assert bad_limit["error"] == "INVALID_LIMIT"
    assert all(
        result["radar_admission"] == "BLOCKED" and result["live_trade"] is False
        for result in (bad_symbol, bad_timeframe, bad_limit)
    )


def test_livefeed_health_exposes_safe_provider_callback_latency(tmp_path):
    heartbeat = _heartbeat()
    heartbeat["adapter_diagnostics"] = {
        "provider_callback_latency_ms_last": 4.25,
        "provider_callback_latency_sample_count": 17,
    }
    status = _write(tmp_path / "heartbeat.json", heartbeat)
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())

    result = read_us_livefeed_health(status, snapshot, now_utc=NOW)

    assert result["status"] == "HEALTHY"
    assert result["provider_callback_latency_ms"] == 4.25
    assert result["provider_callback_latency_sample_count"] == 17
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_livefeed_health_rejects_malformed_provider_callback_latency(tmp_path):
    heartbeat = _heartbeat()
    heartbeat["adapter_diagnostics"] = {
        "provider_callback_latency_ms_last": -1,
        "provider_callback_latency_sample_count": 1,
    }
    status = _write(tmp_path / "heartbeat.json", heartbeat)
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())

    result = read_us_livefeed_health(status, snapshot, now_utc=NOW)

    assert result["status"] == "INVALID"
    assert result["error"] == "INVALID_PROVIDER_CALLBACK_LATENCY"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False

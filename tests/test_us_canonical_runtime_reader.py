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
        "symbols": ["US.AMD", "US.QQQ"],
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


def test_fresh_publication_does_not_launder_old_provider_bar(tmp_path):
    payload = _snapshot(emitted_at=NOW - timedelta(seconds=2))
    payload["latest_source_timestamp_utc"] = (NOW - timedelta(minutes=10)).isoformat()
    payload["latest_received_at_utc"] = (NOW - timedelta(seconds=2)).isoformat()
    snapshot = _write(tmp_path / "snapshot.json", payload)

    result = read_us_market_bars(
        "AMD", timeframe="1m", limit=1, path=snapshot, now_utc=NOW
    )

    assert result["status"] == "STALE"
    assert result["source_age_seconds"] == 600
    assert result["publication_age_seconds"] == 2


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


def test_livefeed_health_projects_fresh_forming_push_without_promoting_closure(tmp_path):
    heartbeat = _heartbeat()
    heartbeat["market_state_us"] = "PRE_MARKET_BEGIN"
    heartbeat["latest_push_observations"] = {
        "US.AMD": {
            "symbol": "US.AMD",
            "time_key": "2026-10-07 00:39:00",
            "received_at_utc": (NOW - timedelta(seconds=2)).isoformat(),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 12.0,
            "bar_closure": "UNPROVEN",
            "private_field": "must not escape",
        },
        "HK.00700": {
            "symbol": "HK.00700",
            "time_key": "2026-10-07 00:39:00",
            "received_at_utc": NOW.isoformat(),
            "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0,
        },
    }
    status = _write(tmp_path / "heartbeat.json", heartbeat)
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())

    result = read_us_livefeed_health(status, snapshot, now_utc=NOW)

    observation = result["latest_push_observations"]["US.AMD"]
    assert result["latest_push_status"] == "FRESH"
    assert observation["close"] == 100.5
    assert observation["volume"] == 12.0
    assert observation["bar_closure"] == "UNPROVEN"
    assert observation["research_eligible"] is False
    assert observation["freshness_status"] == "FRESH"
    assert "private_field" not in observation
    assert "HK.00700" not in result["latest_push_observations"]
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_livefeed_health_marks_old_forming_push_stale_and_drops_invalid_ohlcv(tmp_path):
    heartbeat = _heartbeat()
    heartbeat["latest_push_observations"] = {
        "US.AMD": {
            "symbol": "US.AMD",
            "time_key": "2026-10-07 00:37:00",
            "received_at_utc": (NOW - timedelta(minutes=3)).isoformat(),
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.0, "volume": 12.0,
        },
        "US.QQQ": {
            "symbol": "US.QQQ",
            "time_key": "2026-10-07 00:37:00",
            "received_at_utc": NOW.isoformat(),
            "open": 100.0, "high": 100.0, "low": 101.0,
            "close": 100.0, "volume": 12.0,
        },
    }
    status = _write(tmp_path / "heartbeat.json", heartbeat)
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())

    result = read_us_livefeed_health(status, snapshot, now_utc=NOW)

    assert result["latest_push_status"] == "STALE"
    assert result["latest_push_observations"]["US.AMD"]["freshness_status"] == "STALE"
    assert "US.QQQ" not in result["latest_push_observations"]
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


def test_postclose_historical_repair_evidence_is_visible_without_promoting(tmp_path):
    heartbeat = _heartbeat()
    heartbeat["postclose_reconciliation"] = {
        "session_date": "2026-10-07",
        "status": "PASS_HISTORICAL_ONLY",
        "reason": "HISTORICAL_TERMINAL_RECONCILIATION",
        "provider_requests": 1,
        "seeded_count": 1,
        "historical_query": True,
        "currentness_proven": False,
        "bar_closure_promotion_authorized": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "symbols": {"US.AMD": {"status": "PASS_HISTORICAL_ONLY"}},
    }
    status = _write(tmp_path / "heartbeat.json", heartbeat)
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())
    out = read_us_livefeed_health(status, snapshot, now_utc=NOW)
    evidence = out["postclose_reconciliation"]
    assert evidence["status"] == "PASS_HISTORICAL_ONLY"
    assert evidence["provider_requests"] == 1
    assert evidence["seeded_count"] == 1
    assert evidence["qualified_symbol_count"] == 1
    assert evidence["provider_finality"] == "NOT_VERIFIED"
    assert evidence["bar_closure_promotion_authorized"] is False
    assert out["radar_admission"] == "BLOCKED"


def test_postclose_subtree_cannot_launder_admission_or_fake_cost(tmp_path):
    heartbeat = _heartbeat()
    heartbeat["postclose_reconciliation"] = {
        "status": "PASS_HISTORICAL_ONLY",
        "provider_requests": True,
        "seeded_count": 999,
        "historical_query": True,
        "currentness_proven": True,
        "bar_closure_promotion_authorized": True,
        "radar_admission": "ADMITTED",
        "live_trade": True,
    }
    status = _write(tmp_path / "heartbeat.json", heartbeat)
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())
    out = read_us_livefeed_health(status, snapshot, now_utc=NOW)
    assert out["postclose_reconciliation"]["status"] == "INVALID_EVIDENCE"
    assert out["radar_admission"] == "BLOCKED"
    assert out["live_trade"] is False


def test_postclose_mcp_rejects_yesterday_repair_as_current_session(tmp_path):
    heartbeat = _heartbeat()
    heartbeat["postclose_reconciliation"] = {
        "session_date": "2026-10-05",
        "status": "PASS_HISTORICAL_ONLY",
        "provider_requests": 1,
        "seeded_count": 1,
        "historical_query": True,
        "currentness_proven": False,
        "bar_closure_promotion_authorized": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    status = _write(tmp_path / "heartbeat.json", heartbeat)
    snapshot = _write(tmp_path / "snapshot.json", _snapshot())
    out = read_us_livefeed_health(status, snapshot, now_utc=NOW)
    assert out["postclose_reconciliation"]["status"] == "INVALID_EVIDENCE"
    assert out["radar_admission"] == "BLOCKED"



def test_livefeed_health_realtime_evidence_requires_fresh_provenanced_source(tmp_path):
    fresh = _snapshot(emitted_at=NOW - timedelta(seconds=2))
    fresh["latest_source_timestamp_utc"] = (
        NOW - timedelta(seconds=10)
    ).isoformat()
    status = _write(tmp_path / "status.json", _heartbeat())
    snapshot = _write(tmp_path / "snapshot.json", fresh)
    result = read_us_livefeed_health(status, snapshot, now_utc=NOW)
    assert result["status"] == "HEALTHY"
    assert result["canonical_snapshot_status"] == "PASS"
    assert result["realtime_delivery_evidence"] is True

    # Current heartbeats and export time cannot make a stale provider bar live.
    fresh["latest_source_timestamp_utc"] = (
        NOW - timedelta(minutes=10)
    ).isoformat()
    _write(tmp_path / "snapshot.json", fresh)
    stat = os.stat(snapshot)
    os.utime(snapshot, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    result = read_us_livefeed_health(status, snapshot, now_utc=NOW)
    assert result["status"] == "HEALTHY"
    assert result["canonical_snapshot_status"] == "STALE"
    assert result["canonical_snapshot_age_seconds"] == 600
    assert result["realtime_delivery_evidence"] is False
    assert result["radar_admission"] == "BLOCKED"


def test_realtime_evidence_rejects_unverified_source_identity(tmp_path):
    status = _write(tmp_path / "status.json", _heartbeat())
    snapshot = tmp_path / "snapshot.json"
    payload = _snapshot()
    payload["latest_source_timestamp_utc"] = (
        NOW - timedelta(seconds=5)
    ).isoformat()
    for changed_field in ("repo_sha", "runtime_instance_id"):
        corrupted = dict(payload)
        corrupted[changed_field] = (
            "other-run" if changed_field == "runtime_instance_id" else "b" * 40
        )
        _write(snapshot, corrupted)
        result = read_us_livefeed_health(status, str(snapshot), now_utc=NOW)
        assert result["status"] == "HEALTHY"
        assert result["canonical_snapshot_status"] == "PASS"
        assert result["realtime_delivery_evidence"] is False
        assert result["radar_admission"] == "BLOCKED"

    # Legacy snapshots without source-time provenance cannot establish fresh bars.
    _write(snapshot, _snapshot())
    unknown = read_us_livefeed_health(status, str(snapshot), now_utc=NOW)
    assert unknown["status"] == "HEALTHY"
    assert unknown["realtime_delivery_evidence"] is False


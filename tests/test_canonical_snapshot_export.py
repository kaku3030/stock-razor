import json
from datetime import datetime, timedelta, timezone

import pytest

from data_provider.market_data_adapter import evaluate_health
from src.services.live_feed.canonical_snapshot_export import (
    SCHEMA,
    build_canonical_snapshot_export,
    write_canonical_snapshot_export,
)
from src.services.live_feed.futu_k1m_forming_accumulator import FormingMinuteBar
from src.services.live_feed.futu_research_bridge import closed_futu_minute_to_bar
from src.services.realtime_market_data import RealtimeMarketDataService


START = datetime(2026, 10, 6, 13, 30, tzinfo=timezone.utc)
BLOCKED = evaluate_health(
    freshness=0, completeness=0, timestamp=0, provider=1, continuity=0, cross_check=0,
    quality_flags=("MISSING_BAR", "TIMESTAMP_SEMANTICS_UNVERIFIED"),
)


def service():
    return RealtimeMarketDataService(
        None,
        session_status_provider=lambda _market: "regular",
        provider_health_provider=lambda: BLOCKED,
        max_minutes=120,
        now=lambda: START + timedelta(minutes=30),
    )


def add_minutes(svc, symbol="US.AMD", count=30):
    for i in range(count):
        start = START + timedelta(minutes=i)
        end = start + timedelta(minutes=1)
        minute = FormingMinuteBar(
            symbol, end.astimezone(timezone(timedelta(hours=-4))).replace(tzinfo=None),
            100+i*.1, 101+i*.1, 99+i*.1, 100.5+i*.1, 100+i, 10000+i, True,
        )
        svc.ingest(closed_futu_minute_to_bar(minute, received_at=end + timedelta(seconds=2)))


def payload_for(svc, symbol="US.AMD"):
    snap = svc.snapshot(symbol, as_of=START + timedelta(minutes=30))
    return build_canonical_snapshot_export(
        {symbol: snap},
        runtime_instance_id="runtime-1",
        repo_sha="a"*40,
        sequence=7,
        emitted_at_utc=START + timedelta(minutes=30),
        market_state_us="MORNING",
        cache_session_us="regular",
    )


def test_export_preserves_canonical_timeframes_health_and_safety():
    svc = service()
    add_minutes(svc)
    payload = payload_for(svc)

    assert payload["schema"] == SCHEMA
    assert payload["delivery_mode"] == "UNKNOWN"
    assert payload["bar_closure"] == "UNPROVEN"
    assert payload["radar_admission"] == "BLOCKED"
    assert payload["live_trade"] is False
    symbol = payload["symbols"]["US.AMD"]
    assert len(symbol["timeframes"]["1m"]) == 30
    assert len(symbol["timeframes"]["5m"]) == 6
    assert len(symbol["timeframes"]["15m"]) == 2
    assert len(symbol["timeframes"]["1h"]) == 1
    assert symbol["timeframes"]["1h"][0]["is_complete"] is False
    first = symbol["timeframes"]["1m"][0]
    assert first["provider"] == "futu"
    assert first["feed"] == "opend"
    assert first["is_closed"] and first["is_complete"]
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" in first["quality_flags"]
    assert first["health"]["signal_permission"] == "blocked"


def test_empty_snapshot_is_exportable_without_inventing_bars():
    svc = service()
    payload = payload_for(svc)
    symbol = payload["symbols"]["US.AMD"]
    assert all(symbol["timeframes"][tf] == [] for tf in ("1m", "5m", "15m", "1h"))
    assert symbol["health"]["signal_permission"] == "blocked"


def test_export_rejects_bad_identity_and_symbol_mapping():
    svc = service()
    snap = svc.snapshot("US.AMD", as_of=START)
    common = dict(
        snapshots={"US.NVDA": snap},
        runtime_instance_id="runtime-1",
        repo_sha="a"*40,
        sequence=0,
        emitted_at_utc=START,
        market_state_us="MORNING",
        cache_session_us="regular",
    )
    with pytest.raises(ValueError, match="mapping key"):
        build_canonical_snapshot_export(**common)
    common["snapshots"] = {"US.AMD": snap}
    common["repo_sha"] = "short"
    with pytest.raises(ValueError, match="exact 40-character"):
        build_canonical_snapshot_export(**common)


def test_atomic_writer_produces_valid_json_and_no_tmp(tmp_path):
    svc = service()
    add_minutes(svc, count=15)
    payload = payload_for(svc)
    destination = tmp_path / "canonical-market-snapshot.json"
    write_canonical_snapshot_export(destination, payload)
    loaded = json.loads(destination.read_text("utf-8"))
    assert loaded["schema"] == SCHEMA
    assert loaded["symbols"]["US.AMD"]["timeframes"]["15m"]
    assert not (tmp_path / "canonical-market-snapshot.json.tmp").exists()

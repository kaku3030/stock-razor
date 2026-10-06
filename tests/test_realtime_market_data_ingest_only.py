from datetime import datetime, timedelta, timezone

import pytest

from data_provider.market_data_adapter import Bar, SignalPermission, evaluate_health
from src.services.realtime_market_data import RealtimeMarketDataService


START = datetime(2026, 10, 5, 13, 30, tzinfo=timezone.utc)
BLOCKED = evaluate_health(
    freshness=0.5,
    completeness=1,
    timestamp=0.5,
    provider=1,
    continuity=0.5,
    cross_check=0.5,
    quality_flags=("TIMESTAMP_SEMANTICS_UNVERIFIED",),
)


def bar(index: int) -> Bar:
    start = START + timedelta(minutes=index)
    return Bar(
        symbol="US.AMD",
        market="us",
        asset_type="stock",
        timeframe="1m",
        bar_start=start,
        bar_end=start + timedelta(minutes=1),
        open=100 + index,
        high=101 + index,
        low=99 + index,
        close=100.5 + index,
        volume=100 + index,
        amount=10000 + index,
        provider="futu",
        feed="opend",
        source_timestamp=start + timedelta(minutes=1),
        received_at=start + timedelta(minutes=1, seconds=1),
        session="regular",
        is_closed=True,
        is_complete=True,
        health=BLOCKED,
        quality_flags=BLOCKED.quality_flags,
    )


def service(*, session="regular") -> RealtimeMarketDataService:
    return RealtimeMarketDataService(
        None,
        session_status_provider=lambda _market: session,
        provider_health_provider=lambda: BLOCKED,
        max_minutes=60,
    )


def test_ingest_only_mode_requires_explicit_session_and_health_evidence():
    with pytest.raises(ValueError, match="ingest-only mode"):
        RealtimeMarketDataService(None)

    with pytest.raises(ValueError, match="ingest-only mode"):
        RealtimeMarketDataService(
            None,
            session_status_provider=lambda _market: "regular",
        )

    with pytest.raises(ValueError, match="ingest-only mode"):
        RealtimeMarketDataService(
            None,
            provider_health_provider=lambda: BLOCKED,
        )


def test_ingest_only_mode_disables_provider_seed_and_subscribe():
    svc = service()

    with pytest.raises(RuntimeError, match="cannot seed"):
        svc.seed("US.AMD")
    with pytest.raises(RuntimeError, match="cannot subscribe"):
        svc.subscribe(["US.AMD"])


def test_empty_ingest_only_snapshot_uses_explicit_provider_health_evidence():
    snapshot = service().snapshot("US.AMD", as_of=START)

    assert snapshot.minute_bars == ()
    assert snapshot.health == BLOCKED
    assert snapshot.health.signal_permission is SignalPermission.BLOCKED


def test_ingest_only_snapshot_uses_same_canonical_aggregation_path():
    svc = service()
    for index in range(5):
        assert svc.ingest(bar(index)) is True

    snapshot = svc.snapshot("US.AMD", as_of=START + timedelta(minutes=5))

    assert len(snapshot.minute_bars) == 5
    assert len(snapshot.bars_5m) == 1
    aggregate = snapshot.bars_5m[0]
    assert aggregate.bar_start == START
    assert aggregate.bar_end == START + timedelta(minutes=5)
    assert aggregate.open == 100
    assert aggregate.close == 104.5
    assert aggregate.provider == "futu"
    assert aggregate.feed == "opend"
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" in aggregate.quality_flags
    assert aggregate.health.signal_permission is SignalPermission.BLOCKED


def test_ingest_only_session_evidence_still_applies_staleness_without_upgrading_blocked():
    svc = service(session="regular")
    svc.ingest(bar(0))

    snapshot = svc.snapshot("US.AMD", as_of=START + timedelta(minutes=5))

    assert "STALE" in snapshot.minute_bars[-1].quality_flags
    assert snapshot.health.signal_permission is SignalPermission.BLOCKED


def test_ingest_only_provider_health_cannot_upgrade_blocked_bar_evidence():
    good_provider_health = evaluate_health(
        freshness=1,
        completeness=1,
        timestamp=1,
        provider=1,
        continuity=1,
        cross_check=1,
    )
    svc = RealtimeMarketDataService(
        None,
        session_status_provider=lambda _market: "regular",
        provider_health_provider=lambda: good_provider_health,
        max_minutes=60,
    )
    svc.ingest(bar(0))

    snapshot = svc.snapshot(
        "US.AMD",
        as_of=START + timedelta(minutes=1),
    )

    assert snapshot.health.signal_permission is SignalPermission.BLOCKED
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" in snapshot.health.quality_flags
    assert snapshot.minute_bars[-1].health.signal_permission is SignalPermission.BLOCKED

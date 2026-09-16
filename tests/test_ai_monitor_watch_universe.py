from datetime import datetime, timezone

import pytest

from src.services.ai_monitor.watch_universe import (
    ActiveWatchUniverse,
    RadarWatchContext,
    WatchIdentity,
    WatchLifecycle,
    WatchSource,
)


NOW = datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)


def test_union_keeps_symbol_active_until_all_sources_are_removed() -> None:
    universe = ActiveWatchUniverse()
    identity = WatchIdentity("us", "AMD")

    universe.activate(
        market="us",
        symbol="amd",
        source=WatchSource.PORTFOLIO,
        activated_at=NOW,
    )
    universe.activate(
        market="us",
        symbol="AMD",
        source=WatchSource.RADAR,
        activated_at=NOW,
        radar=RadarWatchContext(candidate_id="us-amd", candidate_status="WATCH"),
    )
    universe.pin(market="us", symbol="AMD", activated_at=NOW)

    watch = universe.get(identity)
    assert watch.is_active is True
    assert watch.source_names == ("PORTFOLIO", "RADAR", "USER_PINNED")

    universe.remove_source(market="us", symbol="AMD", source=WatchSource.PORTFOLIO)
    universe.remove_source(market="us", symbol="AMD", source=WatchSource.RADAR)

    watch = universe.get(identity)
    assert watch.is_active is True
    assert watch.source_names == ("USER_PINNED",)

    watch = universe.unpin(market="us", symbol="AMD")
    assert watch.is_active is False
    assert watch.lifecycle is WatchLifecycle.WATCH_EXPIRED


def test_radar_reconciliation_never_removes_user_pin_or_portfolio_watch() -> None:
    universe = ActiveWatchUniverse()
    qcom = WatchIdentity("us", "QCOM")
    vrt = WatchIdentity("us", "VRT")

    universe.pin(market="us", symbol="QCOM", activated_at=NOW)
    universe.activate(
        market="us",
        symbol="VRT",
        source=WatchSource.PORTFOLIO,
        activated_at=NOW,
    )
    universe.replace_radar(
        {
            qcom: RadarWatchContext(
                candidate_id="qcom-1",
                candidate_status="WATCH",
                lifecycle="SETUP_FORMING",
                watch_reason="relative strength improving",
            ),
            vrt: RadarWatchContext(
                candidate_id="vrt-1",
                candidate_status="WATCH",
                lifecycle="NEW_BASE_WATCH",
            ),
        },
        activated_at=NOW,
    )

    universe.replace_radar({}, activated_at=NOW)

    assert universe.get(qcom).source_names == ("USER_PINNED",)
    assert universe.get(vrt).source_names == ("PORTFOLIO",)


def test_portfolio_reconciliation_never_removes_radar_watch() -> None:
    universe = ActiveWatchUniverse()
    anet = WatchIdentity("us", "ANET")
    universe.replace_radar(
        {
            anet: RadarWatchContext(
                candidate_id="anet-1",
                candidate_status="WATCH",
                lifecycle="EARLY_DETECTION",
            )
        },
        activated_at=NOW,
    )
    universe.replace_portfolio([anet], activated_at=NOW)
    universe.replace_portfolio([], activated_at=NOW)

    watch = universe.get(anet)
    assert watch.is_active is True
    assert watch.source_names == ("RADAR",)


def test_snapshot_contains_non_position_radar_candidates() -> None:
    universe = ActiveWatchUniverse()
    universe.replace_portfolio(
        [WatchIdentity("us", "AMD")],
        activated_at=NOW,
    )
    universe.replace_radar(
        {
            WatchIdentity("us", "QCOM"): RadarWatchContext(
                candidate_id="qcom-1",
                candidate_status="WATCH",
            ),
            WatchIdentity("us", "ANET"): RadarWatchContext(
                candidate_id="anet-1",
                candidate_status="WATCH",
            ),
        },
        activated_at=NOW,
    )

    snapshot = universe.snapshot(generated_at=NOW)

    assert snapshot.active_symbols == ("AMD", "ANET", "QCOM")


def test_radar_context_is_rejected_for_non_radar_source() -> None:
    universe = ActiveWatchUniverse()

    with pytest.raises(ValueError, match="radar context"):
        universe.activate(
            market="us",
            symbol="AMD",
            source=WatchSource.PORTFOLIO,
            activated_at=NOW,
            radar=RadarWatchContext(candidate_id="not-allowed"),
        )


def test_naive_activation_timestamp_is_rejected() -> None:
    universe = ActiveWatchUniverse()

    with pytest.raises(ValueError, match="timezone-aware"):
        universe.pin(
            market="us",
            symbol="AMD",
            activated_at=datetime(2026, 9, 16, 0, 0),
        )


def test_archive_removes_all_sources_and_is_terminal_until_reactivated() -> None:
    universe = ActiveWatchUniverse()
    identity = WatchIdentity("us", "VRT")
    universe.pin(market="us", symbol="VRT", activated_at=NOW)

    archived = universe.archive(market="us", symbol="VRT")
    assert archived.lifecycle is WatchLifecycle.ARCHIVED
    assert archived.sources == ()

    reactivated = universe.activate(
        market="us",
        symbol="VRT",
        source=WatchSource.RADAR,
        activated_at=NOW,
        radar=RadarWatchContext(candidate_id="vrt-new-base"),
    )
    assert reactivated.lifecycle is WatchLifecycle.ACTIVE
    assert reactivated.source_names == ("RADAR",)

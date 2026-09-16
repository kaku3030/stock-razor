from datetime import datetime, timezone

from src.services.ai_monitor.live_feed_intent import (
    AI_MONITOR_LIVE_FEED_CONSUMER_ID,
    plan_live_feed_watch_intent,
)
from src.services.ai_monitor.watch_universe import (
    ActiveWatchUniverse,
    RadarWatchContext,
    WatchIdentity,
)


NOW = datetime(2026, 9, 16, 2, 30, tzinfo=timezone.utc)


def test_plan_intent_uses_active_watch_union_not_individual_source_events() -> None:
    universe = ActiveWatchUniverse()
    nvda = WatchIdentity("us", "NVDA")
    universe.pin(market="us", symbol="NVDA", activated_at=NOW)
    universe.replace_radar(
        {nvda: RadarWatchContext(candidate_status="WATCH")},
        activated_at=NOW,
    )

    first = plan_live_feed_watch_intent(
        previous_desired=(),
        snapshot=universe.snapshot(generated_at=NOW),
    )
    assert first.consumer_id == AI_MONITOR_LIVE_FEED_CONSUMER_ID
    assert first.added == (nvda,)

    universe.replace_radar({}, activated_at=NOW)
    second = plan_live_feed_watch_intent(
        previous_desired=first.desired,
        snapshot=universe.snapshot(generated_at=NOW),
    )

    assert second.removed == ()
    assert second.unchanged == (nvda,)


def test_plan_intent_emits_deterministic_add_remove_and_unchanged_sets() -> None:
    universe = ActiveWatchUniverse()
    universe.pin(market="us", symbol="MSFT", activated_at=NOW)
    universe.pin(market="cn", symbol="159363", activated_at=NOW)
    previous = (
        WatchIdentity("us", "AAPL"),
        WatchIdentity("us", "MSFT"),
    )

    delta = plan_live_feed_watch_intent(
        previous_desired=previous,
        snapshot=universe.snapshot(generated_at=NOW),
    )

    assert delta.desired == (
        WatchIdentity("cn", "159363"),
        WatchIdentity("us", "MSFT"),
    )
    assert delta.added == (WatchIdentity("cn", "159363"),)
    assert delta.removed == (WatchIdentity("us", "AAPL"),)
    assert delta.unchanged == (WatchIdentity("us", "MSFT"),)


def test_plan_intent_is_pure_and_repeatable() -> None:
    universe = ActiveWatchUniverse()
    universe.pin(market="us", symbol="NVDA", activated_at=NOW)
    snapshot = universe.snapshot(generated_at=NOW)

    first = plan_live_feed_watch_intent(previous_desired=(), snapshot=snapshot)
    second = plan_live_feed_watch_intent(previous_desired=(), snapshot=snapshot)

    assert first == second

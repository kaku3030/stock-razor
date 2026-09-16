from datetime import datetime, timezone

import pytest

from src.services.ai_monitor.subscription_reconciler import (
    SubscriptionKnowledge,
    SubscriptionStateUnknownError,
    WatchSubscriptionReconciler,
)
from src.services.ai_monitor.watch_universe import (
    ActiveWatchUniverse,
    RadarWatchContext,
    WatchIdentity,
    WatchUniverseSnapshot,
)


NOW = datetime(2026, 9, 16, 1, 0, tzinfo=timezone.utc)


class FakeAdapter:
    def __init__(self) -> None:
        self.subscribe_calls = []
        self.unsubscribe_calls = []
        self.fail_unsubscribe = False

    def subscribe(self, symbols, timeframe="1m", callback=None):
        self.subscribe_calls.append((tuple(symbols), timeframe, callback))

    def unsubscribe(self, symbols, timeframe="1m"):
        self.unsubscribe_calls.append((tuple(symbols), timeframe))
        if self.fail_unsubscribe:
            raise RuntimeError("provider outcome uncertain")


def _snapshot_with_us_and_cn() -> tuple[ActiveWatchUniverse, WatchUniverseSnapshot]:
    universe = ActiveWatchUniverse()
    universe.pin(market="us", symbol="AAPL", activated_at=NOW)
    universe.replace_radar(
        {
            WatchIdentity("us", "NVDA"): RadarWatchContext(candidate_status="WATCH"),
            WatchIdentity("cn", "159363"): RadarWatchContext(candidate_status="WATCH"),
        },
        activated_at=NOW,
    )
    return universe, universe.snapshot(generated_at=NOW)


def test_reconciler_subscribes_only_active_symbols_for_its_market() -> None:
    universe, snapshot = _snapshot_with_us_and_cn()
    adapter = FakeAdapter()
    callback = lambda bar: None
    reconciler = WatchSubscriptionReconciler(
        adapter,
        market="US",
        callback=callback,
    )

    result = reconciler.reconcile(snapshot)

    assert result.desired == ("AAPL", "NVDA")
    assert result.subscribed == ("AAPL", "NVDA")
    assert result.unsubscribed == ()
    assert result.unchanged == ()
    assert reconciler.known_subscriptions == ("AAPL", "NVDA")
    assert adapter.subscribe_calls == [(('AAPL', 'NVDA'), "1m", callback)]
    assert adapter.unsubscribe_calls == []

    universe.unpin(market="us", symbol="AAPL")
    universe.pin(market="us", symbol="MSFT", activated_at=NOW)
    delta = reconciler.reconcile(universe.snapshot(generated_at=NOW))

    assert delta.subscribed == ("MSFT",)
    assert delta.unsubscribed == ("AAPL",)
    assert delta.unchanged == ("NVDA",)
    assert reconciler.known_subscriptions == ("MSFT", "NVDA")


def test_reconciler_keeps_symbol_when_another_watch_source_remains() -> None:
    universe = ActiveWatchUniverse()
    universe.pin(market="us", symbol="NVDA", activated_at=NOW)
    universe.replace_radar(
        {WatchIdentity("us", "NVDA"): RadarWatchContext(candidate_status="WATCH")},
        activated_at=NOW,
    )
    adapter = FakeAdapter()
    reconciler = WatchSubscriptionReconciler(adapter, market="us", callback=lambda bar: None)
    reconciler.reconcile(universe.snapshot(generated_at=NOW))

    universe.replace_radar({}, activated_at=NOW)
    result = reconciler.reconcile(universe.snapshot(generated_at=NOW))

    assert result.desired == ("NVDA",)
    assert result.unsubscribed == ()
    assert result.unchanged == ("NVDA",)


def test_uncertain_provider_mutation_blocks_blind_retry_until_transport_restart() -> None:
    universe = ActiveWatchUniverse()
    universe.pin(market="us", symbol="NVDA", activated_at=NOW)
    adapter = FakeAdapter()
    reconciler = WatchSubscriptionReconciler(adapter, market="us", callback=lambda bar: None)
    reconciler.reconcile(universe.snapshot(generated_at=NOW))

    adapter.fail_unsubscribe = True
    universe.unpin(market="us", symbol="NVDA")
    with pytest.raises(SubscriptionStateUnknownError, match="uncertain"):
        reconciler.reconcile(universe.snapshot(generated_at=NOW))

    assert reconciler.knowledge is SubscriptionKnowledge.UNKNOWN
    assert len(adapter.unsubscribe_calls) == 1

    with pytest.raises(SubscriptionStateUnknownError, match="restart transport"):
        reconciler.reconcile(universe.snapshot(generated_at=NOW))
    assert len(adapter.unsubscribe_calls) == 1

    adapter.fail_unsubscribe = False
    reconciler.reset_after_transport_restart()
    result = reconciler.reconcile(universe.snapshot(generated_at=NOW))

    assert result.desired == ()
    assert reconciler.knowledge is SubscriptionKnowledge.KNOWN


def test_restart_reconciliation_resubscribes_full_desired_universe() -> None:
    _, snapshot = _snapshot_with_us_and_cn()
    adapter = FakeAdapter()
    reconciler = WatchSubscriptionReconciler(adapter, market="us", callback=lambda bar: None)
    reconciler.reconcile(snapshot)
    assert len(adapter.subscribe_calls) == 1

    reconciler.reset_after_transport_restart()
    result = reconciler.reconcile(snapshot)

    assert result.subscribed == ("AAPL", "NVDA")
    assert len(adapter.subscribe_calls) == 2

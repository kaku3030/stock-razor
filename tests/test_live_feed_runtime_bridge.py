from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from data_provider.live_feed_types import ProviderEvent, ProviderEventKind, SemanticStreamKey
from src.services.live_feed.commands import FakeProviderCommandExecutor
from src.services.live_feed.controller import LiveFeedController
from src.services.live_feed.opend_subscription_manager import (
    OpenDSubscriptionManager,
    OpenDSubscriptionQuota,
)
from src.services.live_feed.runtime_bridge import LiveFeedRuntimeBridge


KEY = SemanticStreamKey("futu", "us", "US.NVDA", "K_1M", "1m")


@dataclass
class Adapter:
    sink: object = None
    calls: list = None

    def __post_init__(self):
        self.calls = []
    def register_event_sink(self, sink):
        self.sink = sink; self.calls.append(("sink",))
    def start(self):
        self.calls.append(("start",))
    def stop(self):
        self.calls.append(("stop",))
    def subscribe_stream(self, key):
        self.calls.append(("subscribe", key))
    def subscribe_streams(self, keys):
        self.calls.append(("subscribe_many", tuple(keys)))
    def unsubscribe_stream(self, key):
        self.calls.append(("unsubscribe", key))


def controller():
    return LiveFeedController(
        runtime_instance_id="r1",
        provider_id="futu",
        command_executor=FakeProviderCommandExecutor(),
    )


def test_bridge_reuses_controller_and_registers_provider_sink():
    c=controller(); a=Adapter(); r=LiveFeedRuntimeBridge(c,a)
    snap=r.start([KEY])
    assert callable(a.sink)
    assert snap.subscribed == (KEY,)
    assert c.desired_registry_snapshot().entries[0].semantic_stream_key == KEY


def test_bridge_reports_events_after_controller_ingress_accepts_them():
    accepted = []
    c=controller(); a=Adapter()
    r=LiveFeedRuntimeBridge(c,a,on_event_accepted=accepted.append)
    r.start([KEY])
    event=ProviderEvent(
        runtime_instance_id="r1",
        provider_id="futu",
        controller_generation=0,
        observed_at_utc=datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc),
        observed_at_monotonic=1.0,
        event_kind=ProviderEventKind.DATA,
        semantic_stream_key=KEY,
    )
    assert a.sink(event).accepted is True
    assert accepted == [event]


def test_bridge_rejects_empty_and_duplicate_start():
    r=LiveFeedRuntimeBridge(controller(),Adapter())
    with pytest.raises(ValueError): r.start([])
    r.start([KEY])
    with pytest.raises(RuntimeError): r.start([KEY])


def test_stop_unsubscribes_and_requests_controller_stop():
    c=controller(); a=Adapter(); r=LiveFeedRuntimeBridge(c,a)
    r.start([KEY]); snap=r.stop()
    assert ("unsubscribe",KEY) in a.calls
    assert ("stop",) in a.calls
    assert snap.controller.stop_requested is True
    assert snap.subscribed == ()


def test_bridge_contains_no_trading_or_delivery_promotion_surface():
    r=LiveFeedRuntimeBridge(controller(),Adapter())
    assert not hasattr(r,"submit_order")
    assert not hasattr(r,"promote_live")


def test_bridge_batches_provider_subscription_for_multiple_streams():
    second = SemanticStreamKey("futu", "us", "US.AMD", "K_1M", "1m")
    a=Adapter(); r=LiveFeedRuntimeBridge(controller(),a)
    snap=r.start([KEY, second])
    assert ("subscribe_many", (KEY, second)) in a.calls
    assert not any(call[0] == "subscribe" for call in a.calls)
    assert snap.subscribed == (KEY, second)


def test_bridge_dynamically_adds_and_removes_stream_through_existing_owner():
    added = SemanticStreamKey("futu", "us", "US.XLV", "K_1M", "1m")
    c=controller(); a=Adapter(); r=LiveFeedRuntimeBridge(c,a)
    r.start([KEY])

    r.subscribe_streams([added, added])
    assert r.snapshot().subscribed == (KEY, added)
    assert c.desired_registry_snapshot().entries[-1].semantic_stream_key == added
    assert ("subscribe_many", (added,)) in a.calls

    r.unsubscribe_stream(added)
    assert r.snapshot().subscribed == (KEY,)
    assert added not in {
        item.semantic_stream_key
        for item in c.desired_registry_snapshot().entries
    }
    assert ("unsubscribe", added) in a.calls


def test_dynamic_provider_subscribe_failure_rolls_back_desired_registry():
    added = SemanticStreamKey("futu", "us", "US.XLV", "K_1M", "1m")
    c=controller(); a=Adapter(); r=LiveFeedRuntimeBridge(c,a)
    r.start([KEY])

    def fail(_keys):
        raise RuntimeError("provider rejected")
    a.subscribe_streams = fail
    with pytest.raises(RuntimeError, match="provider rejected"):
        r.subscribe_stream(added)
    assert r.snapshot().subscribed == (KEY,)
    assert added not in {
        item.semantic_stream_key
        for item in c.desired_registry_snapshot().entries
    }


def test_existing_opend_subscription_manager_can_reconcile_through_bridge():
    added = SemanticStreamKey("futu", "us", "US.XLV", "K_1M", "1m")
    c=controller(); a=Adapter(); r=LiveFeedRuntimeBridge(c,a)
    r.start([KEY])
    manager=OpenDSubscriptionManager(r, runtime_instance_id="r1")
    quota=OpenDSubscriptionQuota(
        total_used=1,
        remaining=20,
        observed_at_utc=datetime.now(timezone.utc),
        verified=True,
    )

    added_result=manager.update_candidates([added], quota=quota)
    assert added_result.status == "APPLIED"
    assert r.snapshot().subscribed == (KEY, added)
    removed_result=manager.update_candidates([])
    assert removed_result.status == "APPLIED"
    assert r.snapshot().subscribed == (KEY,)

def test_start_partial_provider_batch_rolls_back_owner_and_registry():
    """A failed initial batch may already have subscribed its first stream."""
    second = SemanticStreamKey("futu", "us", "US.XLV", "K_1M", "1m")
    c = controller()
    a = Adapter()
    r = LiveFeedRuntimeBridge(c, a)

    def partially_subscribe(keys):
        assert tuple(keys) == (KEY, second)
        a.calls.append(("subscribe_many_partial", tuple(keys)))
        raise RuntimeError("partial provider subscription")

    a.subscribe_streams = partially_subscribe
    with pytest.raises(RuntimeError, match="partial provider subscription"):
        r.start([KEY, second])

    # The bridge must attempt bounded cleanup for every potentially
    # subscribed stream, even when the provider gives no partial ACK list.
    assert ("unsubscribe", KEY) in a.calls
    assert ("unsubscribe", second) in a.calls
    assert ("stop",) in a.calls
    c.process_pending()
    assert c.desired_registry_snapshot().entries == ()
    assert r.snapshot().subscribed == ()

def test_initial_subscribe_observes_committed_desired_registry():
    c = controller()
    a = Adapter()
    r = LiveFeedRuntimeBridge(c, a)
    original = a.subscribe_streams

    def inspect_registry(keys):
        assert KEY in {
            entry.semantic_stream_key
            for entry in c.desired_registry_snapshot().entries
        }
        original(keys)

    a.subscribe_streams = inspect_registry
    r.start([KEY])
    assert r.snapshot().subscribed == (KEY,)


def test_start_rejected_ingress_rolls_back_partial_desired_registry():
    second = SemanticStreamKey("futu", "us", "US.XLV", "K_1M", "1m")
    c = LiveFeedController(
        runtime_instance_id="r1",
        provider_id="futu",
        command_executor=FakeProviderCommandExecutor(),
        control_queue_maxsize=1,
    )
    a = Adapter()
    r = LiveFeedRuntimeBridge(c, a)
    with pytest.raises(RuntimeError, match="desired registry ingress rejected"):
        r.start([KEY, second])
    assert c.desired_registry_snapshot().entries == ()
    assert r.snapshot().subscribed == ()
    # Ingress failed before adapter.start(): no provider cleanup is needed.
    assert ("start",) not in a.calls
    assert ("stop",) not in a.calls
    assert not any(call[0] == "subscribe_many" for call in a.calls)

def test_initial_adapter_start_sees_desired_registry_before_callback():
    c = controller()
    a = Adapter()
    r = LiveFeedRuntimeBridge(c, a)
    original = a.start

    def immediate_start():
        assert KEY in {
            entry.semantic_stream_key
            for entry in c.desired_registry_snapshot().entries
        }
        original()

    a.start = immediate_start
    r.start([KEY])
    assert r.snapshot().subscribed == (KEY,)


def test_partial_adapter_start_failure_rolls_back_desired_registry():
    c = controller()
    a = Adapter()
    r = LiveFeedRuntimeBridge(c, a)

    def partially_start():
        a.calls.append(("start_partial",))
        raise RuntimeError("adapter startup failure")

    a.start = partially_start
    with pytest.raises(RuntimeError, match="adapter startup failure"):
        r.start([KEY])

    assert ("stop",) in a.calls
    assert c.desired_registry_snapshot().entries == ()
    assert r.snapshot().subscribed == ()
    assert not any(call[0] == "subscribe_many" for call in a.calls)

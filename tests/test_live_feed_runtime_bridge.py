from dataclasses import dataclass

import pytest

from data_provider.live_feed_types import SemanticStreamKey
from src.services.live_feed.commands import FakeProviderCommandExecutor
from src.services.live_feed.controller import LiveFeedController
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
    assert a.sink == c.submit_event
    assert snap.subscribed == (KEY,)
    assert c.desired_registry_snapshot().entries[0].key == KEY


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

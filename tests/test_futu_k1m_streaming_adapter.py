from types import SimpleNamespace
import gc
import weakref

import pytest

from data_provider.futu_k1m_streaming_adapter import FutuK1MStreamingAdapter
from data_provider.live_feed_types import DeliveryMode, LifecycleState, ProviderEventKind, SemanticStreamKey
from src.services.live_feed.commands import FakeProviderCommandExecutor
from src.services.live_feed.controller import LiveFeedController
from src.services.live_feed.runtime_bridge import LiveFeedRuntimeBridge


class Frame:
    def __init__(self, rows):
        self._rows = rows
    def to_dict(self, mode):
        assert mode == "records"
        return self._rows


class BaseHandler:
    def on_recv_rsp(self, rsp):
        return 0, rsp


class Context:
    def __init__(self):
        self.handler = None
        self.calls = []
    def set_handler(self, handler):
        self.handler = handler
    def subscribe(self, symbols, subtypes, subscribe_push):
        self.calls.append(("sub", symbols, subtypes, subscribe_push))
        return 0, "ok"
    def unsubscribe(self, symbols, subtypes):
        self.calls.append(("unsub", symbols, subtypes))
        return 0, "ok"


class LifecycleContext(Context):
    def set_handler(self, handler):
        self.handler = weakref.ref(handler)
        return None

    def emit(self, frame):
        handler = self.handler()
        assert handler is not None
        return handler.on_recv_rsp(frame)


class EagerRegistrationContext(LifecycleContext):
    def set_handler(self, handler):
        self.handler = weakref.ref(handler)
        handler.on_recv_rsp(Frame([{"code": "US.AAPL", "time_key": "2026-10-05 10:01:00"}]))
        return None


FT = SimpleNamespace(
    RET_OK=0,
    CurKlineHandlerBase=BaseHandler,
    SubType=SimpleNamespace(K_1M="K_1M"),
)


def key(symbol="US.AAPL"):
    return SemanticStreamKey("futu", "us", symbol, "K_1M", "1m")


def test_k1m_push_is_evidence_only_and_unknown_delivery():
    ctx = Context()
    events = []
    adapter = FutuK1MStreamingAdapter(
        ctx, FT, runtime_instance_id="r1", controller_generation=lambda: 7
    )
    adapter.register_event_sink(events.append)
    adapter.start()
    adapter.subscribe_stream(key())
    ret, _ = ctx.handler.on_recv_rsp(
        Frame([{"code":"US.AAPL","time_key":"2026-10-05 10:01:00","open":1,"close":2,"high":3,"low":1,"volume":9}])
    )
    assert ret == 0
    assert len(events) == 1
    event = events[0]
    assert event.event_kind is ProviderEventKind.DATA
    assert event.delivery_mode is DeliveryMode.UNKNOWN
    assert event.progress_identity_candidate is None
    assert event.provider_timestamp_raw == "2026-10-05 10:01:00"
    assert event.semantic_stream_key == key()
    assert event.diagnostic_fields["bar_state"] == "FORMING_OR_UNKNOWN"
    assert event.diagnostic_fields["bar_closure"] == "UNPROVEN"
    assert event.diagnostic_fields["same_time_key_may_update"] is True
    assert ctx.calls == [("sub", ["US.AAPL"], ["K_1M"], True)]


def test_scope_is_strictly_us_k1m():
    ctx = Context()
    adapter = FutuK1MStreamingAdapter(ctx, FT, runtime_instance_id="r1", controller_generation=lambda: 1)
    adapter.register_event_sink(lambda event: None)
    adapter.start()
    with pytest.raises(ValueError):
        adapter.subscribe_stream(SemanticStreamKey("futu","us","US.AAPL","QUOTE",None))
    with pytest.raises(ValueError):
        adapter.subscribe_stream(SemanticStreamKey("futu","hk","HK.00700","K_1M","1m"))


def test_subscribe_failure_is_explicit():
    class BadContext(Context):
        def subscribe(self, symbols, subtypes, subscribe_push):
            return -1, "permission denied"
    adapter = FutuK1MStreamingAdapter(BadContext(), FT, runtime_instance_id="r1", controller_generation=lambda: 1)
    adapter.register_event_sink(lambda event: None)
    adapter.start()
    with pytest.raises(RuntimeError, match="permission denied"):
        adapter.subscribe_stream(key())


def test_same_time_key_updates_remain_distinct_forming_bar_evidence():
    ctx = Context()
    events = []
    adapter = FutuK1MStreamingAdapter(
        ctx, FT, runtime_instance_id="r1", controller_generation=lambda: 1
    )
    adapter.register_event_sink(events.append)
    adapter.start()
    ctx.handler.on_recv_rsp(Frame([
        {"code":"US.NVDA","time_key":"2026-10-05 10:52:00","close":190.10,"volume":100},
        {"code":"US.NVDA","time_key":"2026-10-05 10:52:00","close":190.20,"volume":120},
    ]))
    assert len(events) == 2
    assert events[0].provider_timestamp_raw == events[1].provider_timestamp_raw
    assert events[0].payload["close"] != events[1].payload["close"]
    assert all(e.progress_identity_candidate is None for e in events)
    assert all(e.diagnostic_fields["bar_closure"] == "UNPROVEN" for e in events)


def test_handler_lifecycle_keeps_delayed_callback_alive_after_context_registration():
    ctx = LifecycleContext()
    events = []
    adapter = FutuK1MStreamingAdapter(ctx, FT, runtime_instance_id="r1", controller_generation=lambda: 1)
    adapter.register_event_sink(events.append)
    adapter.start()
    gc.collect()

    ctx.emit(Frame([{"code": "US.AAPL", "time_key": "2026-10-05 10:01:00"}]))
    assert len(events) == 1
    assert events[0].semantic_stream_key == key()


def test_callback_delivered_during_handler_registration_is_not_dropped():
    ctx = EagerRegistrationContext()
    events = []
    adapter = FutuK1MStreamingAdapter(ctx, FT, runtime_instance_id="r1", controller_generation=lambda: 1)
    adapter.register_event_sink(events.append)

    adapter.start()

    assert len(events) == 1
    assert events[0].provider_timestamp_raw == "2026-10-05 10:01:00"


def test_handler_registration_failure_is_explicit():
    class BadRegistrationContext(Context):
        def set_handler(self, handler):
            return -1

    adapter = FutuK1MStreamingAdapter(BadRegistrationContext(), FT, runtime_instance_id="r1", controller_generation=lambda: 1)
    adapter.register_event_sink(lambda event: None)

    with pytest.raises(RuntimeError, match="handler registration rejected"):
        adapter.start()
    assert adapter._started is False
    assert adapter._handler is None


def test_batch_subscription_matches_proven_opend_call_shape():
    ctx = Context()
    adapter = FutuK1MStreamingAdapter(ctx, FT, runtime_instance_id="r1", controller_generation=lambda: 1)
    adapter.register_event_sink(lambda event: None)
    adapter.start()
    keys = (key("US.AMD"), key("US.NVDA"), key("US.TSLA"), key("US.AAPL"), key("US.QQQ"))
    adapter.subscribe_streams(keys)
    assert ctx.calls == [("sub", ["US.AMD","US.NVDA","US.TSLA","US.AAPL","US.QQQ"], ["K_1M"], True)]


def test_diagnostics_observe_callback_rows_sink_and_subscribe_without_promotion():
    ctx=Context(); events=[]
    adapter=FutuK1MStreamingAdapter(ctx,FT,runtime_instance_id="r1",controller_generation=lambda:1)
    adapter.register_event_sink(events.append); adapter.start(); adapter.subscribe_stream(key())
    ctx.handler.on_recv_rsp(Frame([{"code":"US.AAPL","time_key":"2026-10-05 10:01:00"}]))
    d=adapter.diagnostics()
    assert d["handler_callback_count"] == 1
    assert d["row_count"] == 1
    assert d["sink_emit_count"] == 1
    assert d["last_subscribe_result"] == {"ret":0,"data":"ok"}


def test_explicit_sync_context_evidence_emits_connected_and_subscription_result_without_realtime_claim():
    ctx = Context()
    events = []
    adapter = FutuK1MStreamingAdapter(
        ctx,
        FT,
        runtime_instance_id="r1",
        controller_generation=lambda: 1,
        transport_connected_evidence="OPEND_SYNC_CONTEXT_CONSTRUCTION_RETURNED",
    )
    adapter.register_event_sink(events.append)

    adapter.start()
    adapter.subscribe_stream(key())

    assert [event.event_kind for event in events] == [
        ProviderEventKind.CONNECTED,
        ProviderEventKind.SUBSCRIPTION_RESULT,
    ]
    connected, subscription = events
    assert connected.delivery_mode is DeliveryMode.UNKNOWN
    assert connected.provenance == "CALLER_VERIFIED_TRANSPORT"
    assert connected.diagnostic_fields["transport_evidence"] == "OPEND_SYNC_CONTEXT_CONSTRUCTION_RETURNED"
    assert connected.diagnostic_fields["delivery_qualification"] == "UNPROVEN"
    assert subscription.semantic_stream_key == key()
    assert subscription.payload["accepted"] is True
    assert subscription.delivery_mode is DeliveryMode.UNKNOWN
    assert subscription.diagnostic_fields["administrative_only"] is True


def test_subscription_rejection_emits_negative_administrative_evidence_before_failing_closed():
    class BadContext(Context):
        def subscribe(self, symbols, subtypes, subscribe_push):
            return -1, "permission denied"

    events = []
    adapter = FutuK1MStreamingAdapter(
        BadContext(),
        FT,
        runtime_instance_id="r1",
        controller_generation=lambda: 1,
        transport_connected_evidence="OPEND_SYNC_CONTEXT_CONSTRUCTION_RETURNED",
    )
    adapter.register_event_sink(events.append)
    adapter.start()

    with pytest.raises(RuntimeError, match="permission denied"):
        adapter.subscribe_stream(key())

    assert events[-1].event_kind is ProviderEventKind.SUBSCRIPTION_RESULT
    assert events[-1].payload["accepted"] is False
    assert events[-1].diagnostic_fields["administrative_only"] is True
    assert events[-1].delivery_mode is DeliveryMode.UNKNOWN


def test_runtime_bridge_reaches_connected_only_from_explicit_transport_evidence_and_never_live():
    ctx = Context()
    controller = LiveFeedController(
        runtime_instance_id="r1",
        provider_id="futu",
        command_executor=FakeProviderCommandExecutor(),
    )
    adapter = FutuK1MStreamingAdapter(
        ctx,
        FT,
        runtime_instance_id="r1",
        controller_generation=lambda: controller.snapshot().controller_generation,
        transport_connected_evidence="OPEND_SYNC_CONTEXT_CONSTRUCTION_RETURNED",
    )
    bridge = LiveFeedRuntimeBridge(controller, adapter)

    snapshot = bridge.start((key(),))

    assert snapshot.controller.lifecycle_state is LifecycleState.CONNECTED
    assert snapshot.controller.lifecycle_state is not LifecycleState.LIVE
    assert "UNHANDLED_EVIDENCE_KIND:SUBSCRIPTION_RESULT" in snapshot.controller.findings


def test_arbitrary_transport_claim_cannot_manufacture_connected_evidence():
    with pytest.raises(ValueError, match="unsupported transport connected evidence"):
        FutuK1MStreamingAdapter(
            Context(),
            FT,
            runtime_instance_id="r1",
            controller_generation=lambda: 1,
            transport_connected_evidence="TRUST_ME_CONNECTED",
        )

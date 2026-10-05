from types import SimpleNamespace

import pytest

from data_provider.futu_k1m_streaming_adapter import FutuK1MStreamingAdapter
from data_provider.live_feed_types import DeliveryMode, ProviderEventKind, SemanticStreamKey


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
    assert event.diagnostic_fields["bar_closure"] == "UNKNOWN"
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

from datetime import datetime, timezone

import pytest

from data_provider.live_feed_types import DeliveryMode, SemanticStreamKey
from data_provider.provider_runtime_bindings import EastmoneyProviderBinding, OpenDProviderBinding


NOW = datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)


def test_opend_observed_callback_row_is_bound_without_promoting_delivery():
    received = []
    binding = OpenDProviderBinding(runtime_instance_id="r1", controller_generation=2, sink=received.append)
    key = SemanticStreamKey("moomoo_opend", "US", "AAPL", "QUOTE")
    events = binding.emit_rows([{"code": "AAPL", "update_time": "2026-10-02 21:00:00", "sequence": 4}], key=key, observed_at_utc=NOW, observed_at_monotonic=8.0)
    assert events == received
    assert events[0].delivery_mode is DeliveryMode.UNKNOWN
    assert events[0].payload["entitlement"] == "UNKNOWN"
    assert events[0].observed_at_monotonic == 8.0


def test_eastmoney_row_is_bound_but_fresh_timestamp_is_not_realtime():
    binding = EastmoneyProviderBinding(runtime_instance_id="r1", controller_generation=0)
    key = SemanticStreamKey("eastmoney", "CN", "600519", "QUOTE")
    event = binding.emit_row({"f57": "600519", "f86": 1790989200, "price": 123.4}, key=key, observed_at_utc=NOW)
    assert event.delivery_mode is DeliveryMode.UNKNOWN
    assert event.payload["entitlement"] == "UNKNOWN"
    assert event.progress_identity_candidate is not None


def test_opend_quote_second_resolution_timestamp_is_not_unique_progress():
    binding = OpenDProviderBinding(runtime_instance_id="r1", controller_generation=0)
    key = SemanticStreamKey("moomoo_opend", "US", "AAPL", "QUOTE")
    event = binding.emit_rows(
        [{"code": "AAPL", "data_time": "2026-10-02 20:59:59", "last_price": 1.0}],
        key=key,
        observed_at_utc=NOW,
    )[0]
    assert event.progress_identity_candidate is None


def test_future_provider_timestamp_fails_closed():
    binding = OpenDProviderBinding(runtime_instance_id="r1", controller_generation=0)
    key = SemanticStreamKey("moomoo_opend", "US", "AAPL", "QUOTE")
    with pytest.raises(ValueError, match="future"):
        binding.emit_rows(
            [{"code": "AAPL", "data_time": "2026-10-02 21:00:01"}],
            key=key,
            observed_at_utc=NOW,
        )


@pytest.mark.parametrize("bad", [None, {}, {"code": "MSFT", "update_time": "2026-10-02T21:00:00Z"}, {"code": "AAPL", "update_time": "not-a-time"}])
def test_opend_malformed_or_wrong_identity_fails_closed(bad):
    binding = OpenDProviderBinding(runtime_instance_id="r1", controller_generation=0)
    key = SemanticStreamKey("moomoo_opend", "US", "AAPL", "QUOTE")
    with pytest.raises((TypeError, ValueError)):
        binding.emit_rows([bad] if bad is not None else bad, key=key, observed_at_utc=NOW)


def test_eastmoney_wrong_market_or_identity_fails_closed():
    binding = EastmoneyProviderBinding(runtime_instance_id="r1", controller_generation=0)
    with pytest.raises(ValueError):
        binding.emit_row({"f57": "600519", "f86": 1790989200}, key=SemanticStreamKey("eastmoney", "US", "600519", "QUOTE"), observed_at_utc=NOW)
    with pytest.raises(ValueError):
        binding.emit_row({"f57": "000001", "f86": 1790989200}, key=SemanticStreamKey("eastmoney", "CN", "600519", "QUOTE"), observed_at_utc=NOW)
    with pytest.raises(ValueError):
        binding.emit_row({"f86": 1790989200}, key=SemanticStreamKey("eastmoney", "CN", "600519", "QUOTE"), observed_at_utc=NOW)


def test_opend_sdk_handler_shape_forwards_only_successful_callbacks():
    class Base:
        response = (0, [{"code": "AAPL", "update_time": "2026-10-02 21:00:00"}])

        def on_recv_rsp(self, _rsp):
            return self.response

    class Futu:
        RET_OK = 0
        StockQuoteHandlerBase = Base
        CurKlineHandlerBase = Base

    received = []
    binding = OpenDProviderBinding(runtime_instance_id="r1", controller_generation=0, sink=received.append)
    key = SemanticStreamKey("moomoo_opend", "US", "AAPL", "QUOTE")
    quote_handler, _ = binding.handler_factories(Futu, key=key, observed_at=lambda: NOW)
    ret, _ = quote_handler.on_recv_rsp(object())
    assert ret == Futu.RET_OK
    assert len(received) == 1

    Base.response = (1, "subscription rejected")
    quote_handler.on_recv_rsp(object())
    assert len(received) == 1


def test_opend_kline_timestamp_can_observe_progress_but_does_not_claim_closure():
    binding = OpenDProviderBinding(runtime_instance_id="r1", controller_generation=0)
    key = SemanticStreamKey("moomoo_opend", "US", "AAPL", "K_1M", timeframe="1m")
    event = binding.emit_rows(
        [{"code": "AAPL", "time_key": "2026-10-02 20:59:00", "close": 1.0}],
        key=key,
        observed_at_utc=NOW,
    )[0]
    assert event.progress_identity_candidate is not None
    assert event.payload["entitlement"] == "UNKNOWN"
    assert event.payload.get("is_complete", "UNKNOWN") == "UNKNOWN"


def test_eastmoney_future_timestamp_fails_closed():
    binding = EastmoneyProviderBinding(runtime_instance_id="r1", controller_generation=0)
    key = SemanticStreamKey("eastmoney", "CN", "600519", "QUOTE")
    with pytest.raises(ValueError, match="future"):
        binding.emit_row(
            {"f57": "600519", "f86": 1790989200 + 3600},
            key=key,
            observed_at_utc=NOW,
        )

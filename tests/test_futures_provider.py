from datetime import datetime, timezone

import pandas as pd
import pytest

from data_provider.futures_provider import (
    ActualContinuousMapping,
    RollObservation,
    YahooFuturesHistoryProvider,
    YahooFuturesProviderBinding,
    should_roll,
)
from data_provider.live_feed_types import DeliveryMode, SemanticStreamKey


NOW = datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)


def _row(**overrides):
    row = {
        "provider_timestamp": datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc),
        "open": 100.0,
        "high": 101.0,
        "low": 99.0,
        "close": 100.5,
        "volume": 12,
    }
    row.update(overrides)
    return row


def test_four_instruments_are_explicitly_bound_without_realtime_claim():
    binding = YahooFuturesProviderBinding(runtime_instance_id="r1", controller_generation=0)
    for root in ("GC", "CL", "SI", "HG"):
        event = binding.emit_rows(
            [_row()],
            key=SemanticStreamKey("yahoo_finance", "US_FUTURES", root, "KLINE", timeframe="5m", feed="vendor_continuous"),
            observed_at_utc=NOW,
        )[0]
        assert event.delivery_mode is DeliveryMode.UNKNOWN
        assert event.payload["continuous_semantics"] == "vendor_continuous_candidate"
        assert event.payload["volume_semantics"] == "contracts"


def test_actual_contract_requires_explicit_contract_symbol():
    binding = YahooFuturesProviderBinding(runtime_instance_id="r1", controller_generation=0)
    key = SemanticStreamKey("yahoo_finance", "US_FUTURES", "GC", "KLINE", timeframe="1d", feed="actual_contract")
    with pytest.raises(ValueError, match="contract_symbol"):
        binding.emit_rows([_row()], key=key, observed_at_utc=NOW)


def test_future_timestamp_and_invalid_volume_fail_closed():
    binding = YahooFuturesProviderBinding(runtime_instance_id="r1", controller_generation=0)
    key = SemanticStreamKey("yahoo_finance", "US_FUTURES", "CL", "KLINE", timeframe="15m", feed="vendor_continuous")
    with pytest.raises(ValueError, match="future"):
        binding.emit_rows([_row(provider_timestamp=datetime(2026, 10, 3, 2, 0, tzinfo=timezone.utc))], key=key, observed_at_utc=NOW)
    with pytest.raises(ValueError, match="volume"):
        binding.emit_rows([_row(volume=-1)], key=key, observed_at_utc=NOW)


def test_roll_rule_requires_two_sessions_both_volume_and_open_interest_and_metadata():
    base = dict(
        current_contract="GCZ6",
        next_contract="GCG7",
        current_volume=100,
        next_volume=101,
        current_open_interest=200,
        next_open_interest=201,
    )
    assert not should_roll(RollObservation(**base, consecutive_sessions=1, contract_metadata_verified=True))
    assert not should_roll(RollObservation(**base, consecutive_sessions=2, contract_metadata_verified=False))
    assert should_roll(RollObservation(**base, consecutive_sessions=2, contract_metadata_verified=True))
    assert not should_roll(RollObservation(**{**base, "next_open_interest": None}, consecutive_sessions=2, contract_metadata_verified=True))


def test_mapping_requires_evidence_and_does_not_infer_vendor_symbol():
    mapping = ActualContinuousMapping("GC", "2026-10-02", "GCZ6", "STOCK_RAZOR_GC", "exchange", "published contract metadata")
    assert mapping.actual_contract == "GCZ6"
    with pytest.raises(ValueError):
        ActualContinuousMapping("GC", "2026-10-02", "GCZ6", "STOCK_RAZOR_GC", "", "")


def test_history_wrapper_uses_free_candidate_symbol_and_canonical_event():
    captured = {}

    def download(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame(
            [{"Open": 1, "High": 2, "Low": 0.5, "Close": 1.5, "Volume": 4}],
            index=pd.DatetimeIndex([datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc)]),
        )

    provider = YahooFuturesHistoryProvider(runtime_instance_id="r1", controller_generation=0, download=download)
    events = provider.fetch("HG", "1H", observed_at_utc=NOW)
    assert captured["tickers"] == "HG=F"
    assert captured["interval"] == "1h"
    assert events[0].semantic_stream_key.feed == "vendor_continuous"


def test_actual_history_requires_month_and_preserves_mapping_fields():
    def download(**_kwargs):
        return pd.DataFrame(
            [{"Open": 1, "High": 2, "Low": 0.5, "Close": 1.5, "Volume": 4}],
            index=pd.DatetimeIndex([datetime(2026, 10, 2, 21, 0, tzinfo=timezone.utc)]),
        )

    provider = YahooFuturesHistoryProvider(runtime_instance_id="r1", controller_generation=0, download=download)
    with pytest.raises(ValueError, match="contract_month"):
        provider.fetch("SI", "1d", observed_at_utc=NOW, actual_contract="SIZ6")
    event = provider.fetch("SI", "1d", observed_at_utc=NOW, actual_contract="SIZ6", contract_month="2026-12")[0]
    assert event.payload["contract_symbol"] == "SIZ6"
    assert event.payload["continuous_semantics"] == "explicit_actual_contract"

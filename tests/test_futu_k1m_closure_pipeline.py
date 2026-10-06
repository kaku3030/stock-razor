from datetime import datetime, timezone

import pytest

from data_provider.live_feed_types import (
    BindingStrength,
    ControlPlaneState,
    ProviderEvent,
    ProviderEventKind,
    SemanticStreamKey,
    freeze_normalized_payload,
)
from data_provider.market_data_adapter import SignalPermission
from src.services.live_feed.commands import FakeProviderCommandExecutor
from src.services.live_feed.controller import AppliedDataEvidence, LiveFeedController
from src.services.live_feed.futu_k1m_closure_pipeline import (
    FutuK1MClosurePipeline,
)


OBSERVED = datetime(2026, 10, 5, 14, 53, 2, tzinfo=timezone.utc)
KEY = SemanticStreamKey("futu", "us", "US.AMD", "K_1M", "1m")


def row(
    time_key: str,
    close: float = 100.5,
    *,
    code: str = "US.AMD",
    volume: float = 10,
):
    return {
        "code": code,
        "time_key": time_key,
        "open": 100,
        "high": max(101, close),
        "low": 99,
        "close": close,
        "volume": volume,
        "turnover": 1000,
    }


def raw_event(
    payload,
    *,
    key=KEY,
    kind=ProviderEventKind.DATA,
    generation=1,
):
    return ProviderEvent(
        runtime_instance_id="r1",
        provider_id="futu",
        controller_generation=generation,
        observed_at_utc=OBSERVED,
        observed_at_monotonic=1.0,
        event_kind=kind,
        semantic_stream_key=key,
        payload=(
            freeze_normalized_payload(payload)
            if payload is not None
            else None
        ),
        provider_timestamp_raw=(
            str(payload.get("time_key")) if payload else None
        ),
        provenance="PUSH",
    )


def event(payload, *, key=KEY, kind=ProviderEventKind.DATA):
    return AppliedDataEvidence(
        event=raw_event(payload, key=key, kind=kind),
        desired_registry_revision_at_apply=1,
        stream_subscription_epoch_at_apply=1,
        control_plane_state_at_apply=ControlPlaneState.DESIRED,
        binding_strength_at_apply=BindingStrength.UNVERIFIED,
    )


def test_raw_provider_event_cannot_bypass_writer_applied_boundary():
    pipeline = FutuK1MClosurePipeline()

    with pytest.raises(TypeError, match="writer-applied"):
        pipeline.consume_event(raw_event(row("2026-10-05 10:52:00")))


def test_controller_writer_egress_chains_into_closure_pipeline():
    controller = LiveFeedController(
        runtime_instance_id="r1",
        provider_id="futu",
        command_executor=FakeProviderCommandExecutor(),
        now_utc=lambda: OBSERVED,
    )
    controller.request_add_desired(KEY)
    controller.process_pending()
    pipeline = FutuK1MClosurePipeline()

    controller.submit_event(
        raw_event(row("2026-10-05 10:52:00", 100.8), generation=0)
    )
    controller.process_pending()
    first = controller.drain_applied_data_for_consumer()
    assert len(first) == 1
    assert pipeline.consume_event(first[0]).status == "FORMING"

    controller.submit_event(
        raw_event(row("2026-10-05 10:53:00", 101.2), generation=0)
    )
    controller.process_pending()
    second = controller.drain_applied_data_for_consumer()
    assert len(second) == 1
    assert pipeline.consume_event(second[0]).status == "CLOSED_QUEUED"
    bars = pipeline.drain_closed()
    assert len(bars) == 1
    assert bars[0].bar_end == datetime(2026, 10, 5, 14, 52, tzinfo=timezone.utc)
    assert bars[0].health.signal_permission is SignalPermission.BLOCKED


def test_same_label_updates_remain_forming_and_do_not_queue_history():
    pipeline = FutuK1MClosurePipeline()

    first = pipeline.consume_event(
        event(row("2026-10-05 10:52:00", 100.5, volume=10))
    )
    update = pipeline.consume_event(
        event(row("2026-10-05 10:52:00", 100.8, volume=20))
    )

    assert first.status == "FORMING"
    assert update.status == "FORMING"
    assert pipeline.drain_closed() == ()
    assert pipeline.diagnostics()["event_count"] == 2


def test_next_end_label_queues_exactly_one_closure_proven_canonical_bar():
    pipeline = FutuK1MClosurePipeline()
    pipeline.consume_event(
        event(row("2026-10-05 10:52:00", 100.8, volume=20))
    )

    result = pipeline.consume_event(
        event(row("2026-10-05 10:53:00", 101.2, volume=5))
    )
    bars = pipeline.drain_closed()

    assert result.status == "CLOSED_QUEUED"
    assert result.closed_bar_queued is True
    assert len(bars) == 1
    bar = bars[0]
    assert bar.symbol == "US.AMD"
    assert bar.bar_start == datetime(2026, 10, 5, 14, 51, tzinfo=timezone.utc)
    assert bar.bar_end == datetime(2026, 10, 5, 14, 52, tzinfo=timezone.utc)
    assert bar.source_timestamp == bar.bar_end
    assert bar.close == 100.8
    assert bar.volume == 20
    assert bar.is_closed and bar.is_complete
    assert "TIMESTAMP_SEMANTICS_UNVERIFIED" in bar.quality_flags
    assert bar.health.signal_permission is SignalPermission.BLOCKED
    assert pipeline.drain_closed() == ()


def test_out_of_order_data_is_blocked_without_escaping_or_emitting_bar():
    pipeline = FutuK1MClosurePipeline()
    pipeline.consume_event(event(row("2026-10-05 10:53:00", 101)))

    result = pipeline.consume_event(event(row("2026-10-05 10:52:00", 100)))

    assert result.status == "BLOCKED"
    assert result.reason == "ValueError"
    assert pipeline.drain_closed() == ()
    diagnostics = pipeline.diagnostics()
    assert diagnostics["blocked_count"] == 1
    assert diagnostics["recent_errors"][-1] == {
        "symbol": "US.AMD",
        "reason": "ValueError",
    }


def test_malformed_data_is_blocked_without_provider_callback_exception():
    pipeline = FutuK1MClosurePipeline()
    malformed = row("2026-10-05 10:52:00")
    malformed.pop("open")

    result = pipeline.consume_event(event(malformed))

    assert result.status == "BLOCKED"
    assert result.reason == "KeyError"
    assert pipeline.drain_closed() == ()


def test_payload_symbol_mismatch_fails_closed_before_accumulator():
    pipeline = FutuK1MClosurePipeline()

    result = pipeline.consume_event(
        event(row("2026-10-05 10:52:00", code="US.NVDA"))
    )

    assert result.status == "BLOCKED"
    assert result.reason == "PAYLOAD_SYMBOL_MISMATCH"
    assert pipeline.diagnostics()["event_count"] == 0
    assert pipeline.drain_closed() == ()


def test_non_data_and_out_of_scope_streams_are_ignored():
    pipeline = FutuK1MClosurePipeline()
    non_data = pipeline.consume_event(
        event(
            row("2026-10-05 10:52:00"),
            kind=ProviderEventKind.HEARTBEAT,
        )
    )
    wrong_key = SemanticStreamKey("futu", "us", "US.AMD", "K_5M", "5m")
    out_of_scope = pipeline.consume_event(
        event(row("2026-10-05 10:52:00"), key=wrong_key)
    )

    assert non_data.status == "IGNORED"
    assert out_of_scope.status == "IGNORED"
    assert pipeline.diagnostics()["event_count"] == 0


def test_missing_payload_is_blocked_and_diagnostic_queue_is_bounded():
    pipeline = FutuK1MClosurePipeline(max_diagnostics=2)
    for _ in range(3):
        result = pipeline.consume_event(event(None))
        assert result.status == "BLOCKED"

    diagnostics = pipeline.diagnostics()
    assert diagnostics["blocked_count"] == 3
    assert len(diagnostics["recent_errors"]) == 2


def test_symbols_are_isolated_and_each_close_independently():
    pipeline = FutuK1MClosurePipeline()
    nvda_key = SemanticStreamKey("futu", "us", "US.NVDA", "K_1M", "1m")
    pipeline.consume_event(
        event(row("2026-10-05 10:52:00", code="US.AMD"))
    )
    pipeline.consume_event(
        event(
            row("2026-10-05 10:52:00", code="US.NVDA"),
            key=nvda_key,
        )
    )
    pipeline.consume_event(
        event(row("2026-10-05 10:53:00", code="US.AMD"))
    )
    pipeline.consume_event(
        event(
            row("2026-10-05 10:53:00", code="US.NVDA"),
            key=nvda_key,
        )
    )

    bars = pipeline.drain_closed()
    assert [bar.symbol for bar in bars] == ["US.AMD", "US.NVDA"]
    assert all(bar.is_closed and bar.is_complete for bar in bars)


def test_closed_queue_is_bounded_and_fails_closed_without_silent_overwrite():
    pipeline = FutuK1MClosurePipeline(max_pending_closed=1)
    pipeline.consume_event(event(row("2026-10-05 10:52:00", 100.5)))
    first_close = pipeline.consume_event(event(row("2026-10-05 10:53:00", 101.0)))
    blocked = pipeline.consume_event(event(row("2026-10-05 10:54:00", 101.5)))

    assert first_close.status == "CLOSED_QUEUED"
    assert blocked.status == "BLOCKED"
    assert blocked.reason == "CLOSED_QUEUE_FULL"
    diagnostics = pipeline.diagnostics()
    assert diagnostics["blocked_count"] == 1
    assert diagnostics["queued_closed_count"] == 1
    assert diagnostics["recent_errors"][-1] == {
        "symbol": "US.AMD",
        "reason": "CLOSED_QUEUE_FULL",
    }
    bars = pipeline.drain_closed()
    assert len(bars) == 1
    assert bars[0].bar_end == datetime(2026, 10, 5, 14, 52, tzinfo=timezone.utc)


def test_closed_queue_limit_must_be_positive():
    try:
        FutuK1MClosurePipeline(max_pending_closed=0)
    except ValueError as exc:
        assert "max_pending_closed" in str(exc)
    else:
        raise AssertionError("non-positive closed queue limit must fail")

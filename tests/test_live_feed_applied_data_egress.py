from datetime import datetime, timezone

import pytest

from data_provider.live_feed_types import (
    BindingStrength,
    ControlPlaneState,
    ProviderEvent,
    ProviderEventKind,
    SemanticStreamKey,
)
from src.services.live_feed.commands import FakeProviderCommandExecutor
from src.services.live_feed.controller import LiveFeedController


KEY = SemanticStreamKey("futu", "us", "US.AMD", "K_1M", "1m")
OTHER_PROVIDER_KEY = SemanticStreamKey("other", "us", "US.AMD", "K_1M", "1m")
NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)


def controller(**kwargs) -> LiveFeedController:
    return LiveFeedController(
        runtime_instance_id="r1",
        provider_id="futu",
        command_executor=FakeProviderCommandExecutor(),
        now_utc=lambda: NOW,
        **kwargs,
    )


def data_event(*, key=KEY, generation=0) -> ProviderEvent:
    return ProviderEvent(
        runtime_instance_id="r1",
        provider_id="futu",
        controller_generation=generation,
        observed_at_utc=NOW,
        observed_at_monotonic=1.0,
        event_kind=ProviderEventKind.DATA,
        semantic_stream_key=key,
        provider_timestamp_raw="2026-10-06 10:00:00",
        payload={"code": "US.AMD", "time_key": "2026-10-06 10:00:00"},
    )


def test_add_then_data_same_writer_batch_egresses_with_controller_local_binding_facts():
    c = controller()
    c.request_add_desired(KEY)
    c.submit_event(data_event())

    assert c.process_pending() == 2
    drained = c.drain_applied_data_for_consumer()

    assert len(drained) == 1
    evidence = drained[0]
    assert evidence.event.local_enqueue_seq == 2
    assert evidence.event.semantic_stream_key == KEY
    assert evidence.desired_registry_revision_at_apply == 1
    assert evidence.stream_subscription_epoch_at_apply == 1
    assert evidence.control_plane_state_at_apply is ControlPlaneState.DESIRED
    assert evidence.binding_strength_at_apply is BindingStrength.UNVERIFIED


def test_data_before_add_same_writer_batch_is_not_retroactively_admitted():
    c = controller()
    c.submit_event(data_event())
    c.request_add_desired(KEY)

    c.process_pending()

    assert c.drain_applied_data_for_consumer() == []
    assert any(
        "DATA_EGRESS_REJECTED: reason=STREAM_NOT_DESIRED" in finding
        for finding in c.snapshot().findings
    )
    assert c.desired_registry_snapshot().entries[0].semantic_stream_key == KEY


def test_remove_then_data_same_writer_batch_is_rejected():
    c = controller()
    c.request_add_desired(KEY)
    c.process_pending()

    c.request_remove_desired(KEY)
    c.submit_event(data_event())
    c.process_pending()

    assert c.drain_applied_data_for_consumer() == []
    assert any(
        "DATA_EGRESS_REJECTED: reason=STREAM_NOT_DESIRED" in finding
        for finding in c.snapshot().findings
    )


def test_data_then_remove_same_writer_batch_preserves_prior_sequence_fact():
    c = controller()
    c.request_add_desired(KEY)
    c.process_pending()

    c.submit_event(data_event())
    c.request_remove_desired(KEY)
    c.process_pending()

    drained = c.drain_applied_data_for_consumer()
    assert len(drained) == 1
    assert drained[0].event.local_enqueue_seq is not None
    assert c.desired_registry_snapshot().entries == ()


def test_stop_then_data_same_writer_batch_never_egresses():
    c = controller()
    c.request_add_desired(KEY)
    c.process_pending()

    c.request_stop()
    c.submit_event(data_event())
    c.process_pending()

    assert c.drain_applied_data_for_consumer() == []
    assert any("STALE_EVENT_AFTER_STOP: DATA" in f for f in c.snapshot().findings)


def test_stale_generation_data_never_egresses():
    c = controller()
    c.request_add_desired(KEY)
    c.process_pending()

    c.submit_event(data_event(generation=99))
    c.process_pending()

    assert c.drain_applied_data_for_consumer() == []
    assert any(
        "STALE_PROVIDER_EVENT" in f and "CONTROLLER_GENERATION_MISMATCH" in f
        for f in c.snapshot().findings
    )


def test_semantic_stream_provider_mismatch_never_egresses():
    c = controller()
    c.request_add_desired(OTHER_PROVIDER_KEY)
    c.process_pending()

    c.submit_event(data_event(key=OTHER_PROVIDER_KEY))
    c.process_pending()

    assert c.drain_applied_data_for_consumer() == []
    assert any(
        "DATA_EGRESS_REJECTED: reason=SEMANTIC_STREAM_PROVIDER_MISMATCH" in f
        for f in c.snapshot().findings
    )


def test_readd_epoch_is_captured_as_controller_local_unverified_fact():
    c = controller()
    c.request_add_desired(KEY)
    c.process_pending()
    c.request_remove_desired(KEY)
    c.request_readd_incarnation(KEY)
    c.process_pending()

    c.submit_event(data_event())
    c.process_pending()

    evidence = c.drain_applied_data_for_consumer()[0]
    assert evidence.stream_subscription_epoch_at_apply == 2
    assert evidence.binding_strength_at_apply is BindingStrength.UNVERIFIED


def test_applied_data_egress_is_bounded_and_fails_loud_without_overwrite():
    c = controller(applied_data_queue_maxsize=1)
    c.request_add_desired(KEY)
    c.process_pending()

    c.submit_event(data_event())
    c.submit_event(data_event())
    c.process_pending()

    drained = c.drain_applied_data_for_consumer()
    assert len(drained) == 1
    assert any(
        "APPLIED_DATA_EGRESS_LOSS: reason=QUEUE_FULL" in f
        for f in c.snapshot().findings
    )


def test_applied_data_drain_is_bounded_and_validates_argument():
    c = controller()
    c.request_add_desired(KEY)
    c.process_pending()
    c.submit_event(data_event())
    c.submit_event(data_event())
    c.process_pending()

    first = c.drain_applied_data_for_consumer(max_items=1)
    second = c.drain_applied_data_for_consumer(max_items=1)
    assert len(first) == 1
    assert len(second) == 1
    assert c.drain_applied_data_for_consumer() == []

    with pytest.raises(ValueError, match="non-negative"):
        c.drain_applied_data_for_consumer(max_items=-1)


def test_applied_data_queue_size_must_be_positive():
    with pytest.raises(ValueError, match="applied_data_queue_maxsize"):
        controller(applied_data_queue_maxsize=0)


def test_applied_data_peek_is_non_destructive_and_ack_removes_exact_head():
    c = controller()
    c.request_add_desired(KEY)
    c.process_pending()
    c.submit_event(data_event())
    c.process_pending()

    first = c.peek_applied_data_for_consumer()
    second = c.peek_applied_data_for_consumer()

    assert first is not None
    assert second == first
    assert c.ack_applied_data_for_consumer(first) is True
    assert c.peek_applied_data_for_consumer() is None
    assert c.ack_applied_data_for_consumer(first) is False


def test_applied_data_ack_mismatch_is_non_destructive():
    c = controller()
    c.request_add_desired(KEY)
    c.process_pending()
    c.submit_event(data_event())
    c.submit_event(data_event())
    c.process_pending()

    head = c.peek_applied_data_for_consumer()
    assert head is not None
    tail = c.drain_applied_data_for_consumer(max_items=2)[1]

    # Recreate queue so the mismatch test itself is not affected by the
    # destructive compatibility helper used only to obtain a different item.
    c2 = controller()
    c2.request_add_desired(KEY)
    c2.process_pending()
    c2.submit_event(data_event())
    c2.submit_event(data_event())
    c2.process_pending()
    expected_head = c2.peek_applied_data_for_consumer()
    assert expected_head is not None

    with pytest.raises(ValueError, match="does not match queue head"):
        c2.ack_applied_data_for_consumer(tail)

    assert c2.peek_applied_data_for_consumer() == expected_head
    assert c2.ack_applied_data_for_consumer(expected_head) is True


def test_peek_ack_preserves_fifo_across_multiple_items():
    c = controller()
    c.request_add_desired(KEY)
    c.process_pending()
    c.submit_event(data_event())
    c.submit_event(data_event())
    c.process_pending()

    first = c.peek_applied_data_for_consumer()
    assert first is not None
    assert c.ack_applied_data_for_consumer(first) is True

    second = c.peek_applied_data_for_consumer()
    assert second is not None
    assert second.event.local_enqueue_seq > first.event.local_enqueue_seq
    assert c.ack_applied_data_for_consumer(second) is True
    assert c.peek_applied_data_for_consumer() is None

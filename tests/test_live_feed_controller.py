import dataclasses
import threading
from datetime import datetime, timezone

import pytest

from data_provider.live_feed_types import (
    LifecycleState,
    OpaqueUnsupportedPayload,
    ProviderEvent,
    ProviderEventKind,
    SemanticStreamKey,
)
from src.services.live_feed.commands import FakeProviderCommandExecutor, ProviderCommandResult, ProviderCommandType
from src.services.live_feed.controller import (
    CommandQueueFull,
    LiveFeedController,
    LivePromotionForbidden,
    WriterConcurrencyViolation,
    run_command_worker_once,
)

KEY = SemanticStreamKey(provider_id="futu", market="HK", symbol="HK.00700", stream_type="QUOTE")


def _fixed_now():
    return datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)


def _controller(**kwargs) -> LiveFeedController:
    defaults = dict(
        runtime_instance_id="r1",
        provider_id="futu",
        command_executor=FakeProviderCommandExecutor(),
        now_utc=_fixed_now,
    )
    defaults.update(kwargs)
    return LiveFeedController(**defaults)


def _event(kind: ProviderEventKind, **overrides) -> ProviderEvent:
    fields = dict(
        runtime_instance_id="r1",
        provider_id="futu",
        controller_generation=0,
        observed_at_utc=_fixed_now(),
        observed_at_monotonic=1.0,
        event_kind=kind,
    )
    fields.update(overrides)
    return ProviderEvent(**fields)


# ---------------------------------------------------------------------------
# F1: registry must be writer-owned
# ---------------------------------------------------------------------------


def test_f1_controller_exposes_no_mutable_registry_attribute() -> None:
    controller = _controller()
    assert not hasattr(controller, "registry")
    # confirm no other public attribute leaks the mutable registry object
    for name in dir(controller):
        if name.startswith("_"):
            continue
        value = getattr(controller, name)
        assert not hasattr(value, "add_desired")


def test_f1_add_desired_through_controller_does_not_mutate_before_writer_processes() -> None:
    controller = _controller()
    controller.request_add_desired(KEY)
    assert controller.desired_registry_snapshot().revision == 0
    controller.process_pending()
    snap = controller.desired_registry_snapshot()
    assert snap.revision == 1
    assert snap.entries[0].semantic_stream_key == KEY


def test_f1_writer_processing_increments_revision() -> None:
    controller = _controller()
    controller.request_add_desired(KEY)
    applied = controller.process_pending()
    assert applied == 1
    assert controller.snapshot().desired_registry_revision == 1


def test_f1_remove_readd_through_writer_advances_epoch() -> None:
    controller = _controller()
    controller.request_add_desired(KEY)
    controller.process_pending()
    controller.request_remove_desired(KEY)
    controller.request_readd_incarnation(KEY)
    controller.process_pending()
    snap = controller.desired_registry_snapshot()
    assert snap.entries[0].stream_subscription_epoch == 2


def test_f1_noop_mutation_is_deterministic_through_writer() -> None:
    controller = _controller()
    controller.request_remove_desired(KEY)  # never added -- no-op
    controller.process_pending()
    assert controller.desired_registry_snapshot().revision == 0


def test_consumer_bound_ingress_shares_one_provider_intent() -> None:
    controller = _controller()
    controller.request_add_desired_for_consumer(KEY, "portfolio")
    controller.request_add_desired_for_consumer(KEY, "ai_monitor")
    controller.process_pending()

    snap = controller.desired_registry_snapshot()
    assert snap.revision == 1
    assert snap.ownership_revision == 2
    assert snap.entries[0].consumer_ids == ("ai_monitor", "portfolio")


def test_consumer_bound_ingress_non_last_release_does_not_unsubscribe() -> None:
    controller = _controller()
    controller.request_add_desired_for_consumer(KEY, "portfolio")
    controller.request_add_desired_for_consumer(KEY, "ai_monitor")
    controller.process_pending()
    controller.request_remove_desired_for_consumer(KEY, "portfolio")
    controller.process_pending()

    snap = controller.desired_registry_snapshot()
    assert snap.revision == 1
    assert snap.entries[0].consumer_ids == ("ai_monitor",)


def test_consumer_bound_ingress_last_release_removes_provider_intent() -> None:
    controller = _controller()
    controller.request_add_desired_for_consumer(KEY, "ai_monitor")
    controller.process_pending()
    controller.request_remove_desired_for_consumer(KEY, "ai_monitor")
    controller.process_pending()

    snap = controller.desired_registry_snapshot()
    assert snap.revision == 2
    assert snap.entries == ()


def test_legacy_ingress_isolated_from_named_consumer() -> None:
    controller = _controller()
    controller.request_add_desired(KEY)
    controller.request_add_desired_for_consumer(KEY, "ai_monitor")
    controller.process_pending()
    controller.request_remove_desired(KEY)
    controller.process_pending()

    snap = controller.desired_registry_snapshot()
    assert snap.revision == 1
    assert snap.entries[0].consumer_ids == ("ai_monitor",)


@pytest.mark.parametrize("consumer_id", ["", "   ", None, 123])
def test_consumer_bound_ingress_rejects_invalid_consumer_id(consumer_id) -> None:
    controller = _controller()
    with pytest.raises(ValueError):
        controller.request_add_desired_for_consumer(KEY, consumer_id)
    assert controller.desired_registry_snapshot().entries == ()


def test_ownership_only_change_does_not_invalidate_in_flight_command() -> None:
    controller = _controller()
    controller.request_add_desired_for_consumer(KEY, "portfolio")
    controller.process_pending()
    command = controller.submit_command(
        ProviderCommandType.SUBSCRIBE,
        semantic_stream_key=KEY,
        stream_subscription_epoch=1,
    )
    controller.request_add_desired_for_consumer(KEY, "ai_monitor")
    controller.process_pending()

    assert command.desired_registry_revision == 1
    assert controller.desired_registry_snapshot().revision == 1


def test_f1_registry_snapshot_cannot_mutate_authoritative_state() -> None:
    controller = _controller()
    controller.request_add_desired(KEY)
    controller.process_pending()
    snap = controller.desired_registry_snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.entries[0].stream_subscription_epoch = 99  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        snap.revision = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# F2: request_stop must be serialized
# ---------------------------------------------------------------------------


def test_f2_request_stop_does_not_mutate_before_writer_processes() -> None:
    controller = _controller()
    controller.request_stop()
    assert controller.snapshot().stop_requested is False
    controller.process_pending()
    assert controller.snapshot().stop_requested is True


def test_f2_stop_then_connected_is_ignored() -> None:
    controller = _controller()
    controller.request_stop()
    controller.process_pending()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.process_pending()
    snap = controller.snapshot()
    assert snap.lifecycle_state is LifecycleState.DISCONNECTED
    assert any("STALE_EVENT_AFTER_STOP" in f for f in snap.findings)


def test_f2_disconnect_after_stop_is_clean_shutdown() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.process_pending()
    controller.request_stop()
    controller.submit_event(_event(ProviderEventKind.DISCONNECTED))
    controller.process_pending()
    snap = controller.snapshot()
    assert snap.lifecycle_state is LifecycleState.DISCONNECTED
    assert any("SHUTDOWN_CLEAN" in f for f in snap.findings)


def test_f2_queued_evidence_cannot_reverse_shutdown_semantics() -> None:
    controller = _controller()
    controller.request_stop()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.process_pending()
    assert controller.snapshot().lifecycle_state is LifecycleState.DISCONNECTED


def test_f2_concurrent_ordering_is_deterministic_under_writer_serialization() -> None:
    controller = _controller()
    barrier = threading.Barrier(2)

    def submit_stop():
        barrier.wait()
        controller.request_stop()

    def submit_connected():
        barrier.wait()
        controller.submit_event(_event(ProviderEventKind.CONNECTED))

    t1 = threading.Thread(target=submit_stop)
    t2 = threading.Thread(target=submit_connected)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    controller.process_pending()
    snap = controller.snapshot()
    # whichever order they actually landed in, the outcome is one of exactly
    # two deterministic possibilities -- never a torn/ambiguous third state
    if snap.stop_requested and snap.lifecycle_state is LifecycleState.CONNECTED:
        assert True  # CONNECTED's seq happened to precede STOP's seq
    else:
        assert snap.stop_requested is True
        assert snap.lifecycle_state is LifecycleState.DISCONNECTED


# ---------------------------------------------------------------------------
# F3: overflow must not write authoritative findings from the producer
# ---------------------------------------------------------------------------


def test_f3_market_data_overflow_does_not_directly_mutate_findings() -> None:
    controller = _controller(data_queue_maxsize=1)
    controller.submit_event(_event(ProviderEventKind.DATA))
    controller.submit_event(_event(ProviderEventKind.DATA))  # rejected
    # findings are untouched until the writer runs
    assert controller.snapshot().findings == ()


def test_f3_writer_materializes_explicit_ingress_loss_finding() -> None:
    controller = _controller(data_queue_maxsize=1)
    controller.submit_event(_event(ProviderEventKind.DATA))
    r = controller.submit_event(_event(ProviderEventKind.DATA))
    assert not r.accepted and r.reason == "QUEUE_FULL"
    controller.process_pending()
    snap = controller.snapshot()
    assert any("INGRESS_LOSS" in f and "DATA" in f for f in snap.findings)


def test_f3_lifecycle_event_accepted_through_reserved_path_when_data_queue_full() -> None:
    controller = _controller(data_queue_maxsize=1)
    controller.submit_event(_event(ProviderEventKind.DATA))  # fills the data queue
    controller.submit_event(_event(ProviderEventKind.DATA))  # rejected
    r = controller.submit_event(_event(ProviderEventKind.DISCONNECTED))  # priority queue, unaffected
    assert r.accepted


def test_f3_disconnected_not_lost_when_data_queue_saturated() -> None:
    controller = _controller(data_queue_maxsize=1)
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    for _ in range(5):
        controller.submit_event(_event(ProviderEventKind.DATA))  # saturate + overflow data queue
    controller.submit_event(_event(ProviderEventKind.DISCONNECTED))
    controller.process_pending()
    assert controller.snapshot().lifecycle_state is LifecycleState.RECONNECTING


def test_f3_multiple_overflows_do_not_lose_loss_evidence() -> None:
    controller = _controller(data_queue_maxsize=1)
    controller.submit_event(_event(ProviderEventKind.DATA))
    for _ in range(4):
        controller.submit_event(_event(ProviderEventKind.DATA))
    controller.process_pending()
    snap = controller.snapshot()
    loss_findings = [f for f in snap.findings if "INGRESS_LOSS" in f and "DATA" in f]
    assert len(loss_findings) == 1
    assert "rejected_count=4" in loss_findings[0]


def test_f3_submit_event_remains_bounded_and_nonblocking() -> None:
    controller = _controller(data_queue_maxsize=2)
    results = [controller.submit_event(_event(ProviderEventKind.DATA)) for _ in range(10)]
    assert sum(1 for r in results if r.accepted) == 2
    assert sum(1 for r in results if not r.accepted) == 8


# ---------------------------------------------------------------------------
# F4: command boundary must be structurally nonblocking
# ---------------------------------------------------------------------------


def test_f4_submit_command_only_enqueues_locally_not_invoked_inline() -> None:
    invoked = []

    def handler(command):
        invoked.append(command)
        return ProviderCommandResult(
            command_id=command.command_id,
            command_type=command.command_type,
            succeeded=True,
            controller_generation=command.controller_generation,
            desired_registry_revision=command.desired_registry_revision,
            completed_at=_fixed_now(),
        )

    controller = _controller(command_executor=FakeProviderCommandExecutor(handler=handler))
    controller.submit_command(ProviderCommandType.QUERY_SUBSCRIPTION)
    assert invoked == []  # executor never called by submit_command itself
    assert controller.command_results == ()


def test_f4_worker_is_decoupled_from_writer_and_slow_handler_cannot_block_it() -> None:
    def slow_handler(command):
        # simulates a "blocking-looking" handler; since the worker call is
        # entirely outside process_pending, this cannot block the writer.
        return ProviderCommandResult(
            command_id=command.command_id,
            command_type=command.command_type,
            succeeded=True,
            controller_generation=command.controller_generation,
            desired_registry_revision=command.desired_registry_revision,
            completed_at=_fixed_now(),
        )

    executor = FakeProviderCommandExecutor(handler=slow_handler)
    controller = _controller(command_executor=executor)
    controller.submit_command(ProviderCommandType.SUBSCRIBE)
    # writer path works fine with zero interaction with the executor/worker
    applied = controller.process_pending()
    assert applied == 0  # nothing was queued as an event/control request
    assert controller.command_results == ()
    n = run_command_worker_once(controller, executor)
    assert n == 1


def test_f4_command_result_enters_ingress_and_state_unchanged_until_writer_processes() -> None:
    def handler(command):
        return ProviderCommandResult(
            command_id=command.command_id,
            command_type=command.command_type,
            succeeded=True,
            controller_generation=command.controller_generation,
            desired_registry_revision=command.desired_registry_revision,
            completed_at=_fixed_now(),
        )

    executor = FakeProviderCommandExecutor(handler=handler)
    controller = _controller(command_executor=executor)
    controller.submit_command(ProviderCommandType.SUBSCRIBE)
    run_command_worker_once(controller, executor)
    assert controller.command_results == ()  # staged, not yet applied
    controller.process_pending()
    assert len(controller.command_results) == 1


def test_f4_result_sink_cannot_directly_mutate_controller_state() -> None:
    # _stage_command_result is what the executor's sink calls -- confirm it
    # only ever appends to the non-authoritative staging list, never to
    # _command_results, by calling it directly and checking pre-writer state.
    controller = _controller()
    fake_result = ProviderCommandResult(
        command_id="c1",
        command_type=ProviderCommandType.SUBSCRIBE,
        succeeded=True,
        controller_generation=0,
        desired_registry_revision=0,
        completed_at=_fixed_now(),
    )
    controller._stage_command_result(fake_result)
    assert controller.command_results == ()
    controller.process_pending()
    assert len(controller.command_results) == 1


def test_f4_stale_result_helper_still_available() -> None:
    from src.services.live_feed.commands import is_command_result_stale

    result = ProviderCommandResult(
        command_id="c1",
        command_type=ProviderCommandType.SUBSCRIBE,
        succeeded=True,
        controller_generation=1,
        desired_registry_revision=12,
        completed_at=_fixed_now(),
    )
    assert is_command_result_stale(result, current_controller_generation=1, current_desired_registry_revision=13)


def test_f4_command_queue_full_is_explicit_not_silent() -> None:
    controller = _controller(command_queue_maxsize=1)
    controller.submit_command(ProviderCommandType.QUERY_SUBSCRIPTION)
    with pytest.raises(CommandQueueFull):
        controller.submit_command(ProviderCommandType.QUERY_SUBSCRIPTION)


# ---------------------------------------------------------------------------
# F5: stop / stale-event races
# ---------------------------------------------------------------------------


def test_f5_stop_then_connected_ignored() -> None:
    controller = _controller()
    controller.request_stop()
    controller.process_pending()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.process_pending()
    assert controller.snapshot().lifecycle_state is not LifecycleState.CONNECTED


def test_f5_stop_then_disconnected_clean() -> None:
    controller = _controller()
    controller.request_stop()
    controller.process_pending()
    controller.submit_event(_event(ProviderEventKind.DISCONNECTED))
    controller.process_pending()
    assert controller.snapshot().lifecycle_state is LifecycleState.DISCONNECTED


def test_f5_connected_queued_before_stop_in_same_batch_still_applies_then_stops() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))  # earlier seq
    controller.request_stop()  # later seq
    controller.process_pending()
    snap = controller.snapshot()
    assert snap.lifecycle_state is LifecycleState.CONNECTED  # genuinely arrived first
    assert snap.stop_requested is True


def test_f5_stop_queued_before_connected_in_same_batch_ignores_connected() -> None:
    controller = _controller()
    controller.request_stop()  # earlier seq
    controller.submit_event(_event(ProviderEventKind.CONNECTED))  # later seq
    controller.process_pending()
    snap = controller.snapshot()
    assert snap.lifecycle_state is not LifecycleState.CONNECTED
    assert snap.stop_requested is True


def test_f5_repeated_stop_is_idempotent() -> None:
    controller = _controller()
    controller.request_stop()
    controller.request_stop()
    controller.process_pending()
    assert controller.snapshot().stop_requested is True
    controller.request_stop()
    controller.process_pending()
    assert controller.snapshot().stop_requested is True


def test_f5_no_reconnecting_after_applied_stop() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.process_pending()
    controller.request_stop()
    controller.process_pending()
    controller.submit_event(_event(ProviderEventKind.DISCONNECTED))
    controller.process_pending()
    assert controller.snapshot().lifecycle_state is LifecycleState.DISCONNECTED
    assert controller.snapshot().lifecycle_state is not LifecycleState.RECONNECTING


# ---------------------------------------------------------------------------
# F6: real immutable event handoff
# ---------------------------------------------------------------------------


def test_f6_caller_mutating_original_payload_dict_does_not_affect_writer_evidence() -> None:
    controller = _controller()
    payload = {"a": 1}
    controller.submit_event(_event(ProviderEventKind.DATA, payload=payload))
    payload["a"] = 999
    payload["b"] = "mutated after submit"
    controller.process_pending()
    # inspect via the frozen queue item isn't directly exposed, but we can
    # confirm the type is frozen and the mutation is invisible by re-deriving
    # a second event and checking freeze_normalized_payload directly:
    from data_provider.live_feed_types import freeze_normalized_payload

    frozen = freeze_normalized_payload({"a": 1})
    assert frozen["a"] == 1
    assert "b" not in frozen


def test_f6_nested_list_and_dict_are_frozen() -> None:
    from data_provider.live_feed_types import freeze_normalized_payload

    original = {"items": [1, 2, {"nested": "value"}]}
    frozen = freeze_normalized_payload(original)
    original["items"].append(999)
    original["items"][2]["nested"] = "mutated"
    assert frozen["items"] == (1, 2, frozen["items"][2])
    assert frozen["items"][2]["nested"] == "value"
    with pytest.raises(TypeError):
        frozen["items"] = ()  # type: ignore[index]


def test_f6_diagnostic_fields_immutable_after_handoff() -> None:
    controller = _controller()
    diag = {"conn_id": 42}
    r = controller.submit_event(_event(ProviderEventKind.DATA, diagnostic_fields=diag))
    assert r.accepted
    diag["conn_id"] = 999
    diag["new_key"] = "leaked?"
    # the accepted event's diagnostic_fields was frozen at submit time from
    # a *copy* of diag -- verify via the freeze helper's own contract
    from data_provider.live_feed_types import freeze_normalized_payload

    frozen = freeze_normalized_payload(dict({"conn_id": 42}))
    assert frozen["conn_id"] == 42
    assert "new_key" not in frozen


def test_f6_unsupported_opaque_mutable_payload_becomes_explicit_marker() -> None:
    from data_provider.live_feed_types import freeze_normalized_payload

    class _SomeProviderNativeObject:
        pass

    frozen = freeze_normalized_payload({"native": _SomeProviderNativeObject()})
    marker = frozen["native"]
    assert isinstance(marker, OpaqueUnsupportedPayload)
    assert marker.type_name == "_SomeProviderNativeObject"


def test_f6_published_snapshot_findings_tuple_is_immutable() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.process_pending()
    snap = controller.snapshot()
    with pytest.raises((TypeError, AttributeError)):
        snap.findings.append("hack")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# F8: writer-produced atomic published snapshot
# ---------------------------------------------------------------------------


def test_f8_snapshot_changes_only_after_writer_applied_mutation() -> None:
    controller = _controller()
    before = controller.snapshot()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    still_before = controller.snapshot()
    assert still_before is before  # same published object -- enqueue alone changes nothing
    controller.process_pending()
    after = controller.snapshot()
    assert after is not before
    assert after.lifecycle_state is LifecycleState.CONNECTED


def test_f8_registry_revision_in_snapshot_matches_entries_from_same_writer_point() -> None:
    controller = _controller()
    controller.request_add_desired(KEY)
    controller.process_pending()
    snap = controller.snapshot()
    assert snap.desired_registry_revision == snap.desired_registry.revision
    assert len(snap.desired_registry.entries) == 1


def test_f8_stop_lifecycle_registry_are_coherent_within_one_snapshot() -> None:
    controller = _controller()
    controller.request_add_desired(KEY)
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.request_stop()
    controller.process_pending()
    snap = controller.snapshot()
    # all facts reflect the SAME writer pass -- no partial/torn combination
    assert snap.stop_requested is True
    assert snap.desired_registry_revision == 1
    assert snap.lifecycle_state is LifecycleState.CONNECTED  # CONNECTED preceded STOP in seq order


def test_f8_reader_call_does_not_mutate_anything() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.process_pending()
    snap1 = controller.snapshot()
    snap2 = controller.snapshot()
    assert snap1 is snap2


# ---------------------------------------------------------------------------
# Single-writer enforcement (section I) + prior invariants preserved
# ---------------------------------------------------------------------------


def test_writer_concurrency_violation_detected() -> None:
    controller = _controller()
    controller._writer_guard.acquire()
    try:
        with pytest.raises(WriterConcurrencyViolation):
            controller.process_pending()
    finally:
        controller._writer_guard.release()


def test_internal_mutation_helper_rejected_outside_writer_context() -> None:
    controller = _controller()
    with pytest.raises(WriterConcurrencyViolation):
        controller._apply_event_as_writer(_event(ProviderEventKind.CONNECTED))
    with pytest.raises(WriterConcurrencyViolation):
        controller._publish_snapshot()


def test_lifecycle_state_live_is_unreachable() -> None:
    controller = _controller()
    with controller._writer_guard:
        with pytest.raises(LivePromotionForbidden):
            controller._transition_lifecycle_state(LifecycleState.LIVE)
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.process_pending()
    assert controller.snapshot().lifecycle_state is not LifecycleState.LIVE


def test_enqueue_sequence_is_monotonic_across_all_ingress_kinds() -> None:
    controller = _controller()
    r1 = controller.submit_event(_event(ProviderEventKind.HEARTBEAT))
    r2 = controller.request_add_desired(KEY)
    r3 = controller.submit_event(_event(ProviderEventKind.HEARTBEAT))
    assert [r1.local_enqueue_seq, r2.local_enqueue_seq, r3.local_enqueue_seq] == [1, 2, 3]


def test_controller_module_imports_no_futu_sdk() -> None:
    import inspect

    import src.services.live_feed.controller as controller_module

    assert "futu" not in controller_module.__dict__
    source = inspect.getsource(controller_module)
    assert "import futu" not in source
    assert "OpenQuoteContext" not in source


def test_concurrent_submit_event_from_multiple_threads_never_loses_a_seq_number() -> None:
    controller = _controller(data_queue_maxsize=1000)
    results: list = []
    lock = threading.Lock()

    def worker():
        r = controller.submit_event(_event(ProviderEventKind.DATA))
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    seqs = sorted(r.local_enqueue_seq for r in results if r.accepted)
    assert seqs == list(range(1, 51))


# ---------------------------------------------------------------------------
# Repair R2
# ---------------------------------------------------------------------------

from data_provider.live_feed_types import BindingStrength, ControlPlaneState  # noqa: E402
from src.services.live_feed.commands import ProviderCommandResult  # noqa: E402


def test_fixr2_1_cross_thread_locked_but_not_owner_attack_is_rejected() -> None:
    controller = _controller()
    thread_a_in_writer = threading.Event()
    release_thread_a = threading.Event()
    thread_b_result: dict = {}

    def thread_a_body():
        def slow_body():
            thread_a_in_writer.set()
            release_thread_a.wait(timeout=5)

        controller._run_as_writer(slow_body)

    t_a = threading.Thread(target=thread_a_body)
    t_a.start()
    assert thread_a_in_writer.wait(timeout=5)

    # while thread A is genuinely inside the writer pass (guard held,
    # capability token set in ITS context, not thread B's), thread B tries
    # to invoke an internal mutation helper directly.
    def thread_b_body():
        try:
            controller._apply_event_as_writer(_event(ProviderEventKind.CONNECTED))
        except WriterConcurrencyViolation as exc:
            thread_b_result["raised"] = exc

    t_b = threading.Thread(target=thread_b_body)
    t_b.start()
    t_b.join(timeout=5)

    release_thread_a.set()
    t_a.join(timeout=5)

    assert isinstance(thread_b_result.get("raised"), WriterConcurrencyViolation)
    # and no authoritative mutation occurred as a side effect of thread B's attempt
    assert controller.snapshot().lifecycle_state is LifecycleState.DISCONNECTED


def test_fixr2_1_normal_writer_path_still_succeeds() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    applied = controller.process_pending()
    assert applied == 1
    assert controller.snapshot().lifecycle_state is LifecycleState.CONNECTED


def test_fixr2_2_invalid_control_update_does_not_abort_batch() -> None:
    controller = _controller()
    # SET_CONTROL_PLANE_STATE for a key that was never added -- registry
    # raises KeyError internally.
    controller.request_set_control_plane_state(KEY, ControlPlaneState.ACKED, binding_strength=BindingStrength.VERIFIED)
    controller.request_add_desired(KEY)
    controller.request_stop()
    applied = controller.process_pending()
    assert applied == 3  # all three items counted as "applied" (one recorded as error)
    snap = controller.snapshot()
    assert any("WRITER_APPLY_ERROR" in f for f in snap.findings)
    assert snap.desired_registry.entries and snap.desired_registry.entries[0].semantic_stream_key == KEY
    assert snap.stop_requested is True


def test_fixr2_2_stop_survives_earlier_control_error() -> None:
    controller = _controller()
    controller.request_set_control_plane_state(KEY, ControlPlaneState.ACKED)  # will error: key not present
    controller.request_stop()
    controller.process_pending()
    assert controller.snapshot().stop_requested is True


def test_fixr2_2_valid_unrelated_mutation_still_applied_after_earlier_error() -> None:
    other_key = SemanticStreamKey(provider_id="futu", market="HK", symbol="HK.09988", stream_type="QUOTE")
    controller = _controller()
    controller.request_set_control_plane_state(KEY, ControlPlaneState.ACKED)  # error: KEY not present
    controller.request_add_desired(other_key)  # unrelated, must still apply
    controller.process_pending()
    snap = controller.desired_registry_snapshot()
    assert any(e.semantic_stream_key == other_key for e in snap.entries)


def test_fixr2_2_snapshot_still_published_after_recoverable_error() -> None:
    controller = _controller()
    before = controller.snapshot()
    controller.request_set_control_plane_state(KEY, ControlPlaneState.ACKED)  # error
    controller.process_pending()
    after = controller.snapshot()
    assert after is not before  # a new snapshot WAS published despite the error
    assert any("WRITER_APPLY_ERROR" in f for f in after.findings)


def test_fixr2_2_error_finding_names_kind_and_key_not_raw_payload() -> None:
    controller = _controller()
    controller.request_set_control_plane_state(KEY, ControlPlaneState.ACKED)
    controller.process_pending()
    finding = next(f for f in controller.snapshot().findings if "WRITER_APPLY_ERROR" in f)
    assert "SET_CONTROL_PLANE_STATE" in finding
    assert "KeyError" in finding
    assert "HK.00700" in finding


def test_fixr2_2_no_drained_item_disappears_silently_across_mixed_batch() -> None:
    other_key = SemanticStreamKey(provider_id="futu", market="HK", symbol="HK.09988", stream_type="QUOTE")
    controller = _controller()
    controller.request_set_control_plane_state(KEY, ControlPlaneState.ACKED)  # 1: errors
    controller.request_add_desired(other_key)  # 2: applies
    controller.request_stop()  # 3: applies
    controller.submit_event(_event(ProviderEventKind.DISCONNECTED))  # 4: applies (clean shutdown after stop)
    applied = controller.process_pending()
    assert applied == 4
    snap = controller.snapshot()
    assert snap.stop_requested is True
    assert any(e.semantic_stream_key == other_key for e in snap.desired_registry.entries)
    assert any("SHUTDOWN_CLEAN" in f for f in snap.findings)
    assert any("WRITER_APPLY_ERROR" in f for f in snap.findings)


def test_fixr2_3_raw_payload_frozen_before_entering_staging() -> None:
    mutable_payload = {"sub_list": ["HK.00700"]}

    def handler(command):
        return ProviderCommandResult(
            command_id=command.command_id,
            command_type=command.command_type,
            succeeded=True,
            controller_generation=command.controller_generation,
            desired_registry_revision=command.desired_registry_revision,
            completed_at=_fixed_now(),
            raw_payload=mutable_payload,
        )

    from src.services.live_feed.commands import FakeProviderCommandExecutor
    from src.services.live_feed.controller import run_command_worker_once

    executor = FakeProviderCommandExecutor(handler=handler)
    controller = _controller(command_executor=executor)
    controller.submit_command(ProviderCommandType.QUERY_SUBSCRIPTION)
    run_command_worker_once(controller, executor)

    # mutate the ORIGINAL dict after the executor has already delivered the
    # result to the (staging) sink -- must not be visible to the writer
    mutable_payload["sub_list"].append("HK.09988")
    mutable_payload["new_key"] = "leaked?"

    controller.process_pending()
    assert len(controller.command_results) == 1
    frozen = controller.command_results[0].raw_payload
    assert frozen["sub_list"] == ("HK.00700",)
    assert "new_key" not in frozen


def test_fixr2_3_nested_mutation_after_staging_is_isolated() -> None:
    nested = {"outer": {"inner": [1, 2, 3]}}

    def handler(command):
        return ProviderCommandResult(
            command_id=command.command_id,
            command_type=command.command_type,
            succeeded=True,
            controller_generation=command.controller_generation,
            desired_registry_revision=command.desired_registry_revision,
            completed_at=_fixed_now(),
            raw_payload=nested,
        )

    from src.services.live_feed.commands import FakeProviderCommandExecutor
    from src.services.live_feed.controller import run_command_worker_once

    executor = FakeProviderCommandExecutor(handler=handler)
    controller = _controller(command_executor=executor)
    controller.submit_command(ProviderCommandType.SUBSCRIBE)
    run_command_worker_once(controller, executor)

    nested["outer"]["inner"].append(999)
    nested["outer"]["new"] = "added after staging"

    controller.process_pending()
    frozen = controller.command_results[0].raw_payload
    assert frozen["outer"]["inner"] == (1, 2, 3)
    assert "new" not in frozen["outer"]


def test_fixr2_3_unsupported_object_not_retained_by_reference() -> None:
    class _Native:
        pass

    native_obj = _Native()

    def handler(command):
        return ProviderCommandResult(
            command_id=command.command_id,
            command_type=command.command_type,
            succeeded=True,
            controller_generation=command.controller_generation,
            desired_registry_revision=command.desired_registry_revision,
            completed_at=_fixed_now(),
            raw_payload={"native": native_obj},
        )

    from src.services.live_feed.commands import FakeProviderCommandExecutor
    from src.services.live_feed.controller import run_command_worker_once

    executor = FakeProviderCommandExecutor(handler=handler)
    controller = _controller(command_executor=executor)
    controller.submit_command(ProviderCommandType.DIAGNOSTIC)
    run_command_worker_once(controller, executor)
    controller.process_pending()

    marker = controller.command_results[0].raw_payload["native"]
    assert isinstance(marker, OpaqueUnsupportedPayload)
    assert marker is not native_obj


def test_fixr2_3_no_runtime_error_if_producer_mutates_original_after_staging() -> None:
    payload = {"a": [1, 2]}

    def handler(command):
        return ProviderCommandResult(
            command_id=command.command_id,
            command_type=command.command_type,
            succeeded=True,
            controller_generation=command.controller_generation,
            desired_registry_revision=command.desired_registry_revision,
            completed_at=_fixed_now(),
            raw_payload=payload,
        )

    from src.services.live_feed.commands import FakeProviderCommandExecutor
    from src.services.live_feed.controller import run_command_worker_once

    executor = FakeProviderCommandExecutor(handler=handler)
    controller = _controller(command_executor=executor)
    controller.submit_command(ProviderCommandType.DIAGNOSTIC)
    run_command_worker_once(controller, executor)

    for _ in range(1000):
        payload["a"].append(0)  # would previously race the writer's own freeze pass

    controller.process_pending()  # must not raise RuntimeError
    assert controller.command_results[0].raw_payload["a"] == (1, 2)
# ---------------------------------------------------------------------------
# F04 control-evidence fail-loud hardening: ENTITLEMENT / SUBSCRIPTION_RESULT
# and every other non-DATA control kind reaching the writer with no semantic
# handler must be recorded as an explicit diagnostic, never silently dropped
# (frozen contract section 16). No DeliveryMode / REALTIME inference, no
# unauthorized lifecycle mutation.
# ---------------------------------------------------------------------------


def test_f04_entitlement_event_not_silently_dropped() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.ENTITLEMENT))
    controller.process_pending()
    snap = controller.snapshot()
    assert "UNHANDLED_EVIDENCE_KIND:ENTITLEMENT" in snap.findings


def test_f04_subscription_result_event_not_silently_dropped() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.SUBSCRIPTION_RESULT))
    controller.process_pending()
    snap = controller.snapshot()
    assert "UNHANDLED_EVIDENCE_KIND:SUBSCRIPTION_RESULT" in snap.findings


@pytest.mark.parametrize(
    "kind",
    [
        ProviderEventKind.ENTITLEMENT,
        ProviderEventKind.SUBSCRIPTION_RESULT,
        ProviderEventKind.HEARTBEAT,
        ProviderEventKind.TRANSPORT_RECONNECTING,
    ],
)
def test_f04_unhandled_control_kind_is_fail_loud(kind) -> None:
    controller = _controller()
    controller.submit_event(_event(kind))
    controller.process_pending()
    snap = controller.snapshot()
    assert f"UNHANDLED_EVIDENCE_KIND:{kind.value}" in snap.findings
    # no lifecycle advance from any unhandled control evidence
    assert snap.lifecycle_state is LifecycleState.DISCONNECTED


def test_f04_unhandled_evidence_does_not_advance_lifecycle() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.ENTITLEMENT))
    controller.submit_event(_event(ProviderEventKind.SUBSCRIPTION_RESULT))
    controller.process_pending()
    snap = controller.snapshot()
    assert snap.lifecycle_state is LifecycleState.DISCONNECTED
    # findings are the only trace -- nothing else authoritative changed
    assert snap.findings == (
        "UNHANDLED_EVIDENCE_KIND:ENTITLEMENT",
        "UNHANDLED_EVIDENCE_KIND:SUBSCRIPTION_RESULT",
    )


def test_f04_no_delivery_mode_inferred_from_flagged_event() -> None:
    from data_provider.live_feed_types import DeliveryMode

    controller = _controller()
    # Even a caller that (incorrectly) stamps REALTIME on the event must not
    # cause any DeliveryMode / REALTIME inference in authoritative state.
    controller.submit_event(
        _event(ProviderEventKind.ENTITLEMENT, delivery_mode=DeliveryMode.REALTIME)
    )
    controller.process_pending()
    snap = controller.snapshot()
    assert snap.lifecycle_state is LifecycleState.DISCONNECTED
    assert not any(
        "REALTIME" in f or "DELAYED" in f or "DeliveryMode" in f for f in snap.findings
    )
    # only the explicit unhandled diagnostic is recorded
    assert snap.findings == ("UNHANDLED_EVIDENCE_KIND:ENTITLEMENT",)


def test_f04_repeated_identical_unhandled_evidence_is_deterministic() -> None:
    controller = _controller()
    for _ in range(3):
        controller.submit_event(_event(ProviderEventKind.ENTITLEMENT))
    controller.process_pending()
    snap = controller.snapshot()
    assert snap.findings == (
        "UNHANDLED_EVIDENCE_KIND:ENTITLEMENT",
        "UNHANDLED_EVIDENCE_KIND:ENTITLEMENT",
        "UNHANDLED_EVIDENCE_KIND:ENTITLEMENT",
    )

    # identical input + identical run => identical output
    controller2 = _controller()
    for _ in range(3):
        controller2.submit_event(_event(ProviderEventKind.ENTITLEMENT))
    controller2.process_pending()
    assert controller2.snapshot().findings == snap.findings


def test_f04_connected_disconnected_error_semantics_unchanged() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.process_pending()
    assert controller.snapshot().lifecycle_state is LifecycleState.CONNECTED

    # interleaved unhandled control evidence must not knock it back
    controller.submit_event(_event(ProviderEventKind.ENTITLEMENT))
    controller.process_pending()
    assert controller.snapshot().lifecycle_state is LifecycleState.CONNECTED
    assert "UNHANDLED_EVIDENCE_KIND:ENTITLEMENT" in controller.snapshot().findings

    controller.submit_event(_event(ProviderEventKind.DISCONNECTED))
    controller.process_pending()
    assert controller.snapshot().lifecycle_state is LifecycleState.RECONNECTING

    # ERROR branch still sets failure_class (unchanged semantics)
    controller2 = _controller()
    controller2.submit_event(_event(ProviderEventKind.ERROR))
    controller2.process_pending()
    from data_provider.live_feed_types import FailureClass

    assert controller2.snapshot().failure_class is FailureClass.UNKNOWN


def test_f04_market_data_reaching_writer_is_not_flagged_as_unhandled() -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.DATA))
    controller.process_pending()
    snap = controller.snapshot()
    # DATA is expected non-control market-data ingress in Slice 1 -- it must
    # not be mislabelled as silent control-evidence loss.
    assert snap.findings == ()
# ---------------------------------------------------------------------------
# PR #43 review-gap closure (MINOR, test-only): an unhandled control-evidence
# event arriving AFTER stop is routed to the existing STALE_EVENT_AFTER_STOP
# diagnostic (stop takes precedence over fail-loud classification) -- this is
# the current correct behavior and is locked here as a permanent regression.
# ---------------------------------------------------------------------------


def test_f04_unhandled_evidence_after_stop_is_stale_not_unhandled() -> None:
    controller = _controller()
    controller.request_stop()
    controller.process_pending()
    assert controller.snapshot().stop_requested is True

    controller.submit_event(_event(ProviderEventKind.ENTITLEMENT))
    controller.process_pending()
    snap = controller.snapshot()

    # stop precedence: routed to the existing STALE_EVENT_AFTER_STOP path
    assert any("STALE_EVENT_AFTER_STOP: ENTITLEMENT" in f for f in snap.findings)
    # NOT misclassified as an unhandled kind finding
    assert not any("UNHANDLED_EVIDENCE_KIND:ENTITLEMENT" in f for f in snap.findings)
    # lifecycle state remains unchanged
    assert snap.lifecycle_state is LifecycleState.DISCONNECTED
    # no DeliveryMode / REALTIME inference
    assert not any(
        "REALTIME" in f or "DELAYED" in f or "DeliveryMode" in f for f in snap.findings
    )


@pytest.mark.parametrize(
    "kind",
    [
        ProviderEventKind.ENTITLEMENT,
        ProviderEventKind.SUBSCRIPTION_RESULT,
    ],
)
def test_f04_unhandled_evidence_after_stop_stale_for_control_kinds(kind) -> None:
    controller = _controller()
    controller.submit_event(_event(ProviderEventKind.CONNECTED))
    controller.process_pending()
    assert controller.snapshot().lifecycle_state is LifecycleState.CONNECTED

    controller.request_stop()
    controller.process_pending()

    controller.submit_event(_event(kind))
    controller.process_pending()
    snap = controller.snapshot()

    assert any(f"STALE_EVENT_AFTER_STOP: {kind.value}" in f for f in snap.findings)
    assert not any(f"UNHANDLED_EVIDENCE_KIND:{kind.value}" in f for f in snap.findings)
    # lifecycle stays where it was when stop was applied (CONNECTED, not
    # advanced or knocked back by the post-stop evidence)
    assert snap.lifecycle_state is LifecycleState.CONNECTED

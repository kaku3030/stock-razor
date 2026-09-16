"""LiveFeedController skeleton (frozen contract §14, §16, §17) -- Repair R2.

Repair R1 closed the structural single-writer violations found in the
Slice-1 adversarial review (F1-F6, F8): the desired registry, stop
request, ingress-overflow findings, and command results were all
reachable for mutation from arbitrary caller/producer/worker threads,
merely protected by locks (multi-writer-with-mutual-exclusion is NOT the
same thing as single-writer).

Repair R2 fixes three findings the R1 design still left open:

- FIX-R2-1: `_assert_writer_context` used to check only
  `_writer_guard.locked()` -- true whenever *some* thread holds the lock,
  which a second thread could observe as "true" while thread A is mid-pass
  and incorrectly conclude it, too, may mutate. `_writer_guard` and writer
  *ownership proof* are now two separate mechanisms: the guard still
  serializes concurrent `process_pending` passes, while a per-controller
  capability token set into a `contextvars.ContextVar` for the duration of
  the pass (via `_run_as_writer`) is what mutation helpers actually check.
  A second thread's own execution context never has that token set, so it
  fails the assertion even while the guard is held by someone else.
- FIX-R2-2: a recoverable failure applying one drained item (e.g. a
  control-plane update referencing a stream that isn't desired) used to
  raise out of `process_pending` entirely, silently discarding every other
  already-drained item in that batch. Each item is now applied
  individually; a recoverable error (`KeyError`/`ValueError` -- see
  `_RECOVERABLE_ITEM_ERRORS`) becomes an explicit `WRITER_APPLY_ERROR`
  finding and the batch continues in seq order. A genuine
  programming/internal-invariant failure (anything not in that tuple) is
  still allowed to propagate rather than being swallowed.
- FIX-R2-3: `ProviderCommandResult.raw_payload` used to be frozen only
  when the writer materialized staged results, leaving a window between
  staging and materialization where the same mutable object the executor
  built could still be mutated by its caller (or, under concurrent
  mutation, raise mid-freeze and abort the writer pass). Freezing now
  happens in `_stage_command_result`, before the result ever enters
  `_pending_command_results` -- the staging boundary itself owns only
  immutable evidence.

Both R1 and R2 hold: ALL producer-facing entry points only ever enqueue
into thread-safe transport structures and never mutate authoritative
state; every provider event and control request shares one seq counter so
cross-queue ordering (e.g. STOP relative to CONNECTED) is deterministic;
exactly one immutable `LiveFeedControllerSnapshot` is published per writer
pass, so readers never assemble a torn cross-object view.

Still deliberately NOT implemented: CurrentnessBoundary, Continuity,
RecoveryCandidate, entitlement qualification, cache trust revocation,
final health aggregation policy, a full control-plane legal-transition
graph, LIVE promotion (still structurally unreachable), and final
provider-worker isolation (thread-timeout vs. process isolation remains an
open Slice-2 question -- see LIVE_FEED_BLOCKING_EXECUTION_MODEL_V0_1.md).
"""

from __future__ import annotations

import contextvars
import threading
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Callable

from data_provider.live_feed_types import (
    BindingStrength,
    ControlPlaneState,
    FailureClass,
    LifecycleState,
    ProviderEvent,
    ProviderEventKind,
    SemanticStreamKey,
    freeze_normalized_payload,
)

from .commands import ProviderCommand, ProviderCommandExecutor, ProviderCommandResult, ProviderCommandType
from .health import LiveFeedHealth
from .identity import ControllerGeneration, new_command_id
from .registry import LEGACY_DEFAULT_CONSUMER, DesiredRegistrySnapshot, DesiredSubscriptionRegistry


class LivePromotionForbidden(RuntimeError):
    """Raised if any code path attempts to transition LifecycleState to
    LIVE. Slice 1 implements no recovery qualification, so no path may
    ever legitimately produce this transition.
    """


class WriterConcurrencyViolation(RuntimeError):
    """Raised if the single-writer path is entered concurrently, OR if an
    internal mutation helper is invoked outside that path at all (see
    `_assert_writer_context`) -- proof the invariant is structural, not a
    documentation-only promise.
    """


class CommandQueueFull(RuntimeError):
    """Raised by `submit_command` if the local, bounded, nonblocking
    command queue between the writer and a future provider-command
    worker is full. Explicit failure, never a silent drop, never a block.
    """


def _default_now_utc() -> datetime:
    return datetime.now(timezone.utc)


# FIX-R2-1: proves the CURRENT execution context is the one currently
# running this specific controller's writer pass -- Lock.locked() only
# proves *some* thread holds the lock, not that the calling context is
# that thread. A ContextVar is per-OS-thread by default (each thread gets
# its own empty Context unless one is explicitly copied/run, e.g. into an
# asyncio Task), so a second thread reading it while thread A is mid-pass
# sees the default (no capability) even though `_writer_guard.locked()`
# is still True for thread A's pass. This is deliberately per-controller
# (the capability object's identity, not just "a token is set") so two
# different controllers' writer passes on two different threads can never
# be confused with one another either.
_writer_capability_var: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "live_feed_writer_capability", default=None
)

# FIX-R2-2: exceptions considered "recoverable item application errors" --
# e.g. a stale/missing-key control-plane update referencing a stream that
# is no longer (or not yet) desired. These are expected, ordinary
# operational conditions (a late update racing a removal is a normal
# Slice-2 scenario), so they become an explicit WRITER_APPLY_ERROR finding
# and the batch continues. Anything else is treated as a genuine
# programming/internal-invariant failure and is allowed to propagate --
# see the module docstring's "writer exception policy" note.
_RECOVERABLE_ITEM_ERRORS: tuple[type[Exception], ...] = (KeyError, ValueError)


@dataclass(frozen=True)
class EnqueueResult:
    accepted: bool
    local_enqueue_seq: int | None
    reason: str | None = None


class _ControlRequestKind(str, Enum):
    ADD_DESIRED = "ADD_DESIRED"
    REMOVE_DESIRED = "REMOVE_DESIRED"
    READD_INCARNATION = "READD_INCARNATION"
    SET_CONTROL_PLANE_STATE = "SET_CONTROL_PLANE_STATE"
    STOP = "STOP"


@dataclass(frozen=True)
class _ControlRequest:
    """Controller-internal intent request -- NOT provider evidence.
    Carries a seq number from the same shared counter as ProviderEvent so
    the writer can merge-order both kinds deterministically.
    """

    seq: int
    kind: _ControlRequestKind
    semantic_stream_key: SemanticStreamKey | None = None
    control_plane_state: ControlPlaneState | None = None
    binding_strength: BindingStrength | None = None
    consumer_id: str | None = None


@dataclass(frozen=True)
class LiveFeedControllerSnapshot:
    """Immutable published state (frozen contract §16). Exactly one of
    these is built per writer pass and handed to readers -- readers never
    assemble their own view from independently-changing fields.
    """

    runtime_instance_id: str
    provider_id: str
    lifecycle_state: LifecycleState
    failure_class: FailureClass
    controller_generation: int
    desired_registry_revision: int
    stop_requested: bool
    desired_registry: DesiredRegistrySnapshot
    health: LiveFeedHealth
    findings: tuple[str, ...]
    published_at_utc: datetime


class LiveFeedController:
    def __init__(
        self,
        *,
        runtime_instance_id: str,
        provider_id: str,
        command_executor: ProviderCommandExecutor,
        now_utc: Callable[[], datetime] = _default_now_utc,
        data_queue_maxsize: int = 1000,
        priority_queue_maxsize: int = 1000,
        control_queue_maxsize: int = 256,
        command_queue_maxsize: int = 256,
    ) -> None:
        self._runtime_instance_id = runtime_instance_id
        self._provider_id = provider_id
        self._now_utc = now_utc

        self._writer_guard = threading.Lock()

        # --- producer-side ingress transport (NOT authoritative state) ---
        self._ingress_lock = threading.Lock()
        self._next_seq = 1
        self._data_queue: deque[ProviderEvent] = deque()
        self._data_queue_maxsize = data_queue_maxsize
        self._priority_event_queue: deque[ProviderEvent] = deque()
        self._priority_queue_maxsize = priority_queue_maxsize
        self._control_queue: deque[_ControlRequest] = deque()
        self._control_queue_maxsize = control_queue_maxsize
        self._pending_loss: dict[str, int] = {}

        self._command_queue_lock = threading.Lock()
        self._command_queue: deque[ProviderCommand] = deque()
        self._command_queue_maxsize = command_queue_maxsize

        self._pending_results_lock = threading.Lock()
        self._pending_command_results: list[ProviderCommandResult] = []

        # --- authoritative state: written ONLY from inside process_pending
        # (itself serialized by _writer_guard); this lock exists for
        # reader visibility/atomicity, not for admitting a second writer ---
        self._authoritative_lock = threading.Lock()
        self._lifecycle_state = LifecycleState.DISCONNECTED
        self._failure_class = FailureClass.UNKNOWN
        self._controller_generation = ControllerGeneration.initial()
        self._stop_requested = False
        self._findings: list[str] = []
        self._command_results: list[ProviderCommandResult] = []
        self._latest_snapshot: LiveFeedControllerSnapshot | None = None

        self._registry = DesiredSubscriptionRegistry()

        # FIX-R2-1: this controller instance's own writer capability
        # token. Never exposed publicly -- only `process_pending` ever
        # sets it into the current context, and only `_assert_writer_context`
        # ever reads it back.
        self._writer_capability = object()

        self._executor = command_executor
        self._executor.register_result_sink(self._stage_command_result)

        # Publish an initial coherent snapshot before any event is ever
        # processed. Goes through the same guard + context-token path as
        # a real writer pass, so _assert_writer_context holds even here.
        self._run_as_writer(lambda: self._publish_snapshot())

    # ---- writer context: exclusion + ownership proof (FIX-R2-1) ----

    def _run_as_writer(self, body: Callable[[], None]) -> None:
        """Acquire the single-writer exclusion lock AND set this
        controller's writer capability into the current execution
        context for the duration of `body`. These are two distinct
        mechanisms: `_writer_guard` only ensures no two writer passes
        overlap; the context token is what `_assert_writer_context`
        actually checks, and it is scoped to (thread x call), not merely
        "is the lock currently held by someone".
        """

        if not self._writer_guard.acquire(blocking=False):
            raise WriterConcurrencyViolation("process_pending() is already running -- single-writer violation")
        token = _writer_capability_var.set(self._writer_capability)
        try:
            body()
        finally:
            _writer_capability_var.reset(token)
            self._writer_guard.release()

    def _assert_writer_context(self) -> None:
        current = _writer_capability_var.get()
        if current is not self._writer_capability:
            raise WriterConcurrencyViolation(
                "internal mutation helper invoked outside this controller's writer context -- "
                "holding _writer_guard is not sufficient proof of writer ownership"
            )

    # ---- ingress: provider events (any thread may call this) ----

    def submit_event(self, event: ProviderEvent) -> EnqueueResult:
        """Thread-safe, bounded, nonblocking enqueue. Never mutates
        authoritative state -- overflow increments a non-authoritative
        pending-loss counter the writer later converts into an explicit
        finding (F3). Lifecycle/control-kind events (anything but DATA)
        go into a separate, independently-bounded priority queue so
        market-data saturation cannot silently lose them (F3).
        """

        is_data = event.event_kind is ProviderEventKind.DATA
        queue_name = "DATA" if is_data else "PRIORITY"
        with self._ingress_lock:
            target = self._data_queue if is_data else self._priority_event_queue
            maxsize = self._data_queue_maxsize if is_data else self._priority_queue_maxsize
            if len(target) >= maxsize:
                self._pending_loss[queue_name] = self._pending_loss.get(queue_name, 0) + 1
                return EnqueueResult(accepted=False, local_enqueue_seq=None, reason="QUEUE_FULL")
            seq = self._next_seq
            self._next_seq += 1
            stamped = replace(
                event,
                local_enqueue_seq=seq,
                payload=freeze_normalized_payload(event.payload) if event.payload is not None else None,
                diagnostic_fields=freeze_normalized_payload(dict(event.diagnostic_fields)),
            )
            target.append(stamped)
            return EnqueueResult(accepted=True, local_enqueue_seq=seq)

    # ---- ingress: controller-intent control requests (registry + stop) ----

    def _submit_control_request(self, kind: _ControlRequestKind, **fields) -> EnqueueResult:
        with self._ingress_lock:
            if len(self._control_queue) >= self._control_queue_maxsize:
                self._pending_loss["CONTROL"] = self._pending_loss.get("CONTROL", 0) + 1
                return EnqueueResult(accepted=False, local_enqueue_seq=None, reason="QUEUE_FULL")
            seq = self._next_seq
            self._next_seq += 1
            self._control_queue.append(_ControlRequest(seq=seq, kind=kind, **fields))
            return EnqueueResult(accepted=True, local_enqueue_seq=seq)

    def request_add_desired(self, key: SemanticStreamKey) -> EnqueueResult:
        """Compatibility request isolated to the legacy consumer."""
        return self.request_add_desired_for_consumer(key, LEGACY_DEFAULT_CONSUMER)

    def request_remove_desired(self, key: SemanticStreamKey) -> EnqueueResult:
        """Compatibility request isolated to the legacy consumer."""
        return self.request_remove_desired_for_consumer(key, LEGACY_DEFAULT_CONSUMER)

    @staticmethod
    def _validate_consumer_id(consumer_id: str) -> str:
        if not isinstance(consumer_id, str) or not consumer_id.strip():
            raise ValueError("consumer_id is required")
        return consumer_id.strip()

    def request_add_desired_for_consumer(
        self, key: SemanticStreamKey, consumer_id: str
    ) -> EnqueueResult:
        """Enqueue an explicit consumer-owned desired-stream request."""
        consumer = self._validate_consumer_id(consumer_id)
        return self._submit_control_request(
            _ControlRequestKind.ADD_DESIRED,
            semantic_stream_key=key,
            consumer_id=consumer,
        )

    def request_remove_desired_for_consumer(
        self, key: SemanticStreamKey, consumer_id: str
    ) -> EnqueueResult:
        """Enqueue an explicit consumer-owned release request."""
        consumer = self._validate_consumer_id(consumer_id)
        return self._submit_control_request(
            _ControlRequestKind.REMOVE_DESIRED,
            semantic_stream_key=key,
            consumer_id=consumer,
        )

    def request_readd_incarnation(self, key: SemanticStreamKey) -> EnqueueResult:
        return self._submit_control_request(_ControlRequestKind.READD_INCARNATION, semantic_stream_key=key)

    def request_set_control_plane_state(
        self, key: SemanticStreamKey, state: ControlPlaneState, *, binding_strength: BindingStrength | None = None
    ) -> EnqueueResult:
        return self._submit_control_request(
            _ControlRequestKind.SET_CONTROL_PLANE_STATE,
            semantic_stream_key=key,
            control_plane_state=state,
            binding_strength=binding_strength,
        )

    def request_stop(self) -> EnqueueResult:
        """Enqueues a STOP control request -- does NOT mutate
        `stop_requested` directly. Only the writer, applying this request
        in its correct relative order against any concurrently-arriving
        events, sets it (F2).
        """

        return self._submit_control_request(_ControlRequestKind.STOP)

    # ---- readers (any thread; never mutate) ----

    def desired_registry_snapshot(self) -> DesiredRegistrySnapshot:
        """The registry keeps its own internal lock purely to make this
        read safe/consistent while the writer mutates it -- that lock
        does NOT admit a second writer; `add_desired`/`remove_desired`/
        etc. are only ever called from inside the writer path below (F1).
        """

        return self._registry.snapshot()

    def snapshot(self) -> LiveFeedControllerSnapshot:
        with self._authoritative_lock:
            assert self._latest_snapshot is not None
            return self._latest_snapshot

    @property
    def command_results(self) -> tuple[ProviderCommandResult, ...]:
        with self._authoritative_lock:
            return tuple(self._command_results)

    # ---- the single writer path ----

    def process_pending(self) -> int:
        """The ONLY place authoritative state may mutate. Drains all
        three ingress structures, merges them into one globally
        seq-ordered sequence, and applies each item in that exact order
        -- this is what makes cross-queue ordering (e.g. a STOP relative
        to a CONNECTED event) deterministic rather than racy. Publishes
        exactly one new snapshot at the end. Returns the number of items
        applied (including ones that failed with a recoverable error and
        were recorded as a finding rather than applied -- see FIX-R2-2).
        """

        applied_count = 0

        def body() -> None:
            nonlocal applied_count
            with self._ingress_lock:
                control_items = list(self._control_queue)
                self._control_queue.clear()
                priority_items = list(self._priority_event_queue)
                self._priority_event_queue.clear()
                data_items = list(self._data_queue)
                self._data_queue.clear()

            self._materialize_ingress_loss_findings()
            self._materialize_command_results()

            combined: list[tuple[int, object]] = [
                *((item.seq, item) for item in control_items),
                *((item.local_enqueue_seq, item) for item in priority_items),
                *((item.local_enqueue_seq, item) for item in data_items),
            ]
            combined.sort(key=lambda pair: pair[0])

            # FIX-R2-2: each item is applied independently. A recoverable
            # error on one item (e.g. a stale/missing-key control update)
            # must not abort the pass and must not silently discard the
            # remaining already-drained items -- it becomes an explicit
            # finding and processing continues in seq order.
            for seq, item in combined:
                try:
                    if isinstance(item, _ControlRequest):
                        self._apply_control_request_as_writer(item)
                    else:
                        self._apply_event_as_writer(item)
                except _RECOVERABLE_ITEM_ERRORS as exc:
                    self._record_writer_apply_error(item, seq, exc)

            self._publish_snapshot()
            applied_count = len(combined)

        self._run_as_writer(body)
        return applied_count

    def _record_writer_apply_error(self, item: object, seq: int, exc: Exception) -> None:
        """FIX-R2-2: records a recoverable item-application failure as an
        explicit authoritative finding instead of letting it abort the
        rest of the batch. Deliberately excludes raw payload/secret
        content -- only kind, seq, exception type, and (if relevant) the
        semantic stream key are recorded.
        """

        self._assert_writer_context()
        if isinstance(item, _ControlRequest):
            kind_desc = f"control:{item.kind.value}"
        else:
            kind_desc = f"event:{item.event_kind.value}"
        key = getattr(item, "semantic_stream_key", None)
        with self._authoritative_lock:
            self._findings.append(
                f"WRITER_APPLY_ERROR: kind={kind_desc} seq={seq} exception_type={type(exc).__name__} "
                f"semantic_stream_key={key!r}"
            )

    def _materialize_ingress_loss_findings(self) -> None:
        self._assert_writer_context()
        with self._ingress_lock:
            losses = dict(self._pending_loss)
            self._pending_loss.clear()
        if not losses:
            return
        with self._authoritative_lock:
            for queue_name, count in losses.items():
                self._findings.append(f"INGRESS_LOSS: queue={queue_name} rejected_count={count}")

    def _materialize_command_results(self) -> None:
        """Results were already frozen at the staging boundary
        (`_stage_command_result`, FIX-R2-3) -- this only moves them from
        non-authoritative staging into authoritative `_command_results`,
        it does no further freezing/normalization itself.
        """

        self._assert_writer_context()
        with self._pending_results_lock:
            staged = list(self._pending_command_results)
            self._pending_command_results.clear()
        if not staged:
            return
        with self._authoritative_lock:
            self._command_results.extend(staged)

    def _apply_control_request_as_writer(self, request: _ControlRequest) -> None:
        self._assert_writer_context()
        if request.kind is _ControlRequestKind.STOP:
            with self._authoritative_lock:
                self._stop_requested = True
            return
        if request.kind is _ControlRequestKind.ADD_DESIRED:
            self._registry.add_desired_for_consumer(request.semantic_stream_key, request.consumer_id)
        elif request.kind is _ControlRequestKind.REMOVE_DESIRED:
            self._registry.remove_desired_for_consumer(request.semantic_stream_key, request.consumer_id)
        elif request.kind is _ControlRequestKind.READD_INCARNATION:
            self._registry.readd_new_incarnation(request.semantic_stream_key)
        elif request.kind is _ControlRequestKind.SET_CONTROL_PLANE_STATE:
            self._registry.set_control_plane_state(
                request.semantic_stream_key, request.control_plane_state, binding_strength=request.binding_strength
            )

    def _provider_event_relevance_failure(self, event: ProviderEvent) -> str | None:
        """Return the frozen identity invariant violated by `event`, if any.

        Provider callbacks are evidence only. Before any such evidence may
        mutate controller truth, it must belong to this runtime, provider,
        and the controller's current connection generation. This is the
        structural guard for frozen adversarial Case 6 and restart trust
        reset semantics; mismatched evidence remains diagnostic only.
        """

        self._assert_writer_context()
        if event.runtime_instance_id != self._runtime_instance_id:
            return "RUNTIME_INSTANCE_MISMATCH"
        if event.provider_id != self._provider_id:
            return "PROVIDER_MISMATCH"
        if event.controller_generation != self._controller_generation.value:
            return "CONTROLLER_GENERATION_MISMATCH"
        return None

    def _apply_event_as_writer(self, event: ProviderEvent) -> None:
        """Slice 1's only lifecycle logic (F5): once stop has been
        applied, no event may advance lifecycle into an active/recovery
        state -- a DISCONNECTED still resolves cleanly to DISCONNECTED,
        but everything else (a stale CONNECTED, an ERROR, a
        reconnect-oriented event) is recorded as a diagnostic finding only
        and produces no lifecycle mutation.
        """

        self._assert_writer_context()
        relevance_failure = self._provider_event_relevance_failure(event)
        if relevance_failure is not None:
            with self._authoritative_lock:
                self._findings.append(
                    f"STALE_PROVIDER_EVENT: reason={relevance_failure} "
                    f"kind={event.event_kind.value} seq={event.local_enqueue_seq} ignored, no lifecycle change"
                )
            return

        with self._authoritative_lock:
            if self._stop_requested:
                if event.event_kind is ProviderEventKind.DISCONNECTED:
                    self._lifecycle_state = LifecycleState.DISCONNECTED
                    self._findings.append(
                        "SHUTDOWN_CLEAN: disconnect observed after stop_requested, no reconnect scheduled"
                    )
                else:
                    self._findings.append(
                        f"STALE_EVENT_AFTER_STOP: {event.event_kind.value} ignored, no lifecycle change"
                    )
                return

            if event.event_kind is ProviderEventKind.CONNECTED:
                if self._lifecycle_state in (
                    LifecycleState.DISCONNECTED,
                    LifecycleState.RECONNECTING,
                    LifecycleState.CONNECTING,
                ):
                    self._lifecycle_state = LifecycleState.CONNECTED
            elif event.event_kind is ProviderEventKind.DISCONNECTED:
                self._lifecycle_state = LifecycleState.RECONNECTING
            elif event.event_kind is ProviderEventKind.ERROR:
                self._failure_class = FailureClass.UNKNOWN
            elif event.event_kind is ProviderEventKind.DATA:
                # DATA is market-data ingress, not control evidence. Slice 1
                # has no currentness/continuity consumer for it yet, so it
                # reaching the writer is expected and is deliberately not
                # flagged here (its loss already has an explicit
                # INGRESS_LOSS overflow finding). No lifecycle or
                # DeliveryMode semantics are implied.
                pass
            else:
                # Fail-loud (frozen contract section 16): any other control /
                # priority evidence kind that reaches the writer with no
                # semantic handler (ENTITLEMENT, SUBSCRIPTION_RESULT,
                # HEARTBEAT, TRANSPORT_RECONNECTING, or any future kind)
                # must never be silently dropped. This emits an explicit
                # diagnostic finding only -- no lifecycle mutation, no
                # DeliveryMode / REALTIME inference, no authoritative
                # state change.
                self._findings.append(f"UNHANDLED_EVIDENCE_KIND:{event.event_kind.value}")

    def _transition_lifecycle_state(self, new_state: LifecycleState) -> None:
        """Guarded transition primitive. No caller in this module ever
        passes LifecycleState.LIVE -- this check exists so that remains
        true even if a future edit tried to.
        """

        if new_state is LifecycleState.LIVE:
            raise LivePromotionForbidden(
                "Slice 1 implements no recovery qualification; LifecycleState.LIVE is unreachable by design"
            )
        self._assert_writer_context()
        with self._authoritative_lock:
            self._lifecycle_state = new_state

    # ---- provider command boundary (LANE 3, structurally nonblocking) ----

    def submit_command(
        self,
        command_type: ProviderCommandType,
        *,
        semantic_stream_key=None,
        stream_subscription_epoch: int | None = None,
    ) -> ProviderCommand:
        """Enqueues into a LOCAL, bounded command queue only -- this never
        calls `self._executor` (F4). A future worker (real or, for tests,
        `run_command_worker_once`) is the only thing that ever pulls from
        this queue and invokes the executor, on its own thread, decoupled
        from both the writer and from this call.
        """

        snap = self.snapshot()
        command = ProviderCommand(
            runtime_instance_id=self._runtime_instance_id,
            provider_id=self._provider_id,
            controller_generation=snap.controller_generation,
            desired_registry_revision=snap.desired_registry_revision,
            command_id=new_command_id(),
            command_type=command_type,
            created_at=self._now_utc(),
            stream_subscription_epoch=stream_subscription_epoch,
            semantic_stream_key=semantic_stream_key,
        )
        with self._command_queue_lock:
            if len(self._command_queue) >= self._command_queue_maxsize:
                raise CommandQueueFull(f"local command queue full at maxsize={self._command_queue_maxsize}")
            self._command_queue.append(command)
        return command

    def drain_commands_for_worker(self, max_items: int | None = None) -> list[ProviderCommand]:
        """Called by a provider-command worker (never by the writer) to
        pull pending commands for execution. Popping from this queue is
        NOT execution -- it is still just local, in-process handoff.
        """

        with self._command_queue_lock:
            if max_items is None:
                items = list(self._command_queue)
                self._command_queue.clear()
            else:
                items = [self._command_queue.popleft() for _ in range(min(max_items, len(self._command_queue)))]
            return items

    def _stage_command_result(self, result: ProviderCommandResult) -> None:
        """Registered as the executor's result sink. Runs on whatever
        thread the executor/worker delivers a result from -- it must NOT
        touch authoritative state (F4).

        FIX-R2-3: `raw_payload` is frozen HERE, before the result ever
        enters `_pending_command_results`, not later when the writer
        materializes it. Freezing late left a window where the
        executor/provider could still hold and mutate the same mutable
        object the staged result referenced (worse, a concurrent mutation
        during the writer's own freeze pass could raise `RuntimeError`
        and abort the batch). Freezing immediately on receipt means the
        staging boundary itself owns only immutable evidence.
        """

        frozen_result = (
            replace(result, raw_payload=freeze_normalized_payload(result.raw_payload))
            if result.raw_payload is not None
            else result
        )
        with self._pending_results_lock:
            self._pending_command_results.append(frozen_result)

    # ---- snapshot publication (F8: one atomic publication point) ----

    def _publish_snapshot(self) -> None:
        self._assert_writer_context()
        with self._authoritative_lock:
            lifecycle_state = self._lifecycle_state
            failure_class = self._failure_class
            generation = self._controller_generation.value
            stop_requested = self._stop_requested
            findings = tuple(self._findings)
            registry_snapshot = self._registry.snapshot()
            health = LiveFeedHealth(lifecycle_state=lifecycle_state, failure_class=failure_class, findings=findings)
            self._latest_snapshot = LiveFeedControllerSnapshot(
                runtime_instance_id=self._runtime_instance_id,
                provider_id=self._provider_id,
                lifecycle_state=lifecycle_state,
                failure_class=failure_class,
                controller_generation=generation,
                desired_registry_revision=registry_snapshot.revision,
                stop_requested=stop_requested,
                desired_registry=registry_snapshot,
                health=health,
                findings=findings,
                published_at_utc=self._now_utc(),
            )


def run_command_worker_once(controller: LiveFeedController, executor: ProviderCommandExecutor, max_items: int | None = None) -> int:
    """Deterministic, synchronous test-only helper standing in for a
    future dedicated provider-command worker: pulls pending commands from
    the controller's local queue and hands each to `executor.submit`.

    This runs entirely OUTSIDE the writer path -- calling it does not
    require holding (and cannot deadlock against) `process_pending`.
    It is not a production isolation mechanism; see the module docstring
    and commands.py for what remains unresolved for Slice 2.
    """

    commands = controller.drain_commands_for_worker(max_items=max_items)
    for command in commands:
        executor.submit(command)
    return len(commands)

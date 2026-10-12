"""Provider Worker Supervisor V0.1 -- Slice A: contracts and invariants only.

Parent design (frozen): ``LIVE_FEED_PROVIDER_WORKER_DESIGN_FREEZE_V0_1.md``.
Slice A brief: ``LIVE_FEED_PROVIDER_WORKER_SLICE_A_IMPLEMENTATION_BRIEF_V0_1.md``.

This module translates the frozen Provider Worker execution contract into
machine-enforced types and invariants. It contains NO runtime machinery:
no multiprocessing, no subprocess/process launching, no watchers/coordinators,
no IPC, no Futu/provider SDK behavior, no controller lifecycle mutation.

What lives here, exactly:

- the three frozen public enums (``ProviderExecutionOutcome``,
  ``ProviderWorkerEvidenceKind``, ``ProviderExceptionDisposition``) with no
  aliases and no extra members;
- the three frozen immutable domain dataclasses
  (``ResolvedProviderCommandOutcome``, ``ProviderWorkerLifecycleEvidence``,
  ``ProviderWorkerSupervisorConfig``) with exact field order per R3;
- construction-time validation of the frozen invariants (identities,
  worker generation, monotonic/UTC clocks, dispatch/cancellation
  consistency, exact config coverage, no mutable payload aliasing).

The immutable original ``ProviderCommand`` is embedded (never flattened) as
the single command-identity source (freeze §9, R3 §4.3). ``outcome`` /
``kind`` values are execution vocabulary, never ``LifecycleState`` aliases,
never ``FailureClass`` by themselves.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from types import MappingProxyType
from typing import Any

from data_provider.live_feed_types import freeze_normalized_payload

from .commands import ProviderCommand, ProviderCommandType

__all__ = [
    "ProviderExceptionDisposition",
    "ProviderExecutionOutcome",
    "ProviderWorkerEvidenceKind",
    "ProviderWorkerLifecycleEvidence",
    "ProviderWorkerSupervisorConfig",
    "ResolvedProviderCommandOutcome",
]


# ---------------------------------------------------------------------------
# Frozen public enums (exact member names/order/values -- no aliases).
# ---------------------------------------------------------------------------


class ProviderExecutionOutcome(str, Enum):
    """Terminal execution vocabulary for one provider command (freeze §7).

    Exactly one terminal outcome may win per command id. These describe
    execution infrastructure facts only; ``SUCCEEDED`` remains
    administrative provider-call success, never a LIVE/lifecycle alias.
    """

    SUCCEEDED = "SUCCEEDED"
    PROVIDER_REJECTED = "PROVIDER_REJECTED"
    PROVIDER_EXCEPTION = "PROVIDER_EXCEPTION"
    TIMEOUT = "TIMEOUT"
    WORKER_EXITED = "WORKER_EXITED"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    CANCELLED_SHUTDOWN = "CANCELLED_SHUTDOWN"
    CANCELLED_GENERATION_INVALIDATED = "CANCELLED_GENERATION_INVALIDATED"


class ProviderWorkerEvidenceKind(str, Enum):
    """Worker process lifecycle evidence vocabulary (freeze §8).

    Execution facts only -- none of these is a LiveFeed lifecycle alias.
    """

    WORKER_RUNTIME_STARTED = "WORKER_RUNTIME_STARTED"
    WORKER_RUNTIME_READY = "WORKER_RUNTIME_READY"
    WORKER_INIT_FAILED = "WORKER_INIT_FAILED"
    WORKER_STARTUP_TIMEOUT = "WORKER_STARTUP_TIMEOUT"
    WORKER_EXITED = "WORKER_EXITED"
    WORKER_TIMEOUT_KILLED = "WORKER_TIMEOUT_KILLED"
    WORKER_PROTOCOL_FATAL = "WORKER_PROTOCOL_FATAL"
    WORKER_KILL_FAILED = "WORKER_KILL_FAILED"
    WORKER_SHUTDOWN_COMPLETED = "WORKER_SHUTDOWN_COMPLETED"


class ProviderExceptionDisposition(str, Enum):
    """Provider exception fatality classification (freeze §11).

    Default is GENERATION_FATAL. Only an explicit provider-adapter
    classification backed by regression evidence may mark an exception
    family/context WORKER_REUSABLE.
    """

    WORKER_REUSABLE = "WORKER_REUSABLE"
    GENERATION_FATAL = "GENERATION_FATAL"


# ---------------------------------------------------------------------------
# Private, narrow validation helpers (shared by all three dataclasses).
# ---------------------------------------------------------------------------


def _require_non_blank_str(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank string")


def _require_positive_int(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer (bool is rejected)")


def _require_non_negative_int(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer (bool is rejected)")


def _require_finite_positive_float(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite positive number (bool is rejected)")
    if not isfinite(float(value)) or float(value) <= 0.0:
        raise ValueError(f"{name} must be finite and > 0")
    return float(value)


def _require_aware_utc_canonicalizable(name: str, value: Any) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")
    if value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware (naive datetime rejected)")
    try:
        offset = value.utcoffset()
    except Exception as exc:  # pragma: no cover - defensive against broken tzinfo
        raise ValueError(f"{name} has an unusable utcoffset()") from exc
    if offset is None:
        raise ValueError(f"{name} must have a usable utcoffset()")
    # Canonicalizable to UTC must not raise.
    try:
        value.astimezone(timezone.utc)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(f"{name} cannot be canonicalized to UTC") from exc


def _require_local_enqueue_seq(name: str, value: Any) -> None:
    """Stamped-seq rule (Brief §5.1).

    Producer-origin evidence carries ``local_enqueue_seq=None`` at
    construction. ``dataclasses.replace`` re-runs ``__post_init__``, so a
    narrow rule permits only positive stamped sequence values -- arbitrary
    negative/zero values are never silently accepted.
    """
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be None (pre-ingress) or a positive integer stamp")


# Outcomes for which the command MUST have been dispatched (R3 §4.2).
_DISPATCH_REQUIRED_OUTCOMES = frozenset(
    {
        ProviderExecutionOutcome.SUCCEEDED,
        ProviderExecutionOutcome.PROVIDER_REJECTED,
        ProviderExecutionOutcome.PROVIDER_EXCEPTION,
        ProviderExecutionOutcome.TIMEOUT,
        ProviderExecutionOutcome.WORKER_EXITED,
        ProviderExecutionOutcome.PROTOCOL_ERROR,
    }
)


# ---------------------------------------------------------------------------
# Frozen immutable domain types (exact field order per R3 / Slice A brief).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedProviderCommandOutcome:
    """One terminal resolution of one immutable provider command.

    ``command`` is the embedded immutable original (single identity source);
    its runtime/provider identities must equal the envelope identities.
    Provider error fields are evidence strings only -- they never define
    ``FailureClass`` on their own (R3 §4.1).

    ``worker_generation=None`` is only a representational capability for a
    never-dispatched ``CANCELLED_GENERATION_INVALIDATED`` terminal fact. It
    does not itself prove that no generation was ever established; only the
    supervisor that owns generation state may later mint that fact.
    """

    runtime_instance_id: str
    provider_id: str
    worker_generation: int | None
    command: ProviderCommand
    outcome: ProviderExecutionOutcome
    dispatched_at_monotonic_ns: int | None
    terminal_observed_at_monotonic_ns: int
    terminal_at_utc: datetime
    provider_error_code: str | None = None
    provider_error_message: str | None = None
    normalized_provider_payload: Mapping[str, Any] | None = None
    diagnostic_reason: str | None = None
    local_enqueue_seq: int | None = None

    def __post_init__(self) -> None:
        _require_non_blank_str("runtime_instance_id", self.runtime_instance_id)
        _require_non_blank_str("provider_id", self.provider_id)
        if self.worker_generation is None:
            if not (
                self.outcome is ProviderExecutionOutcome.CANCELLED_GENERATION_INVALIDATED
                and self.dispatched_at_monotonic_ns is None
            ):
                raise ValueError(
                    "worker_generation may be None only for an undispatched "
                    "CANCELLED_GENERATION_INVALIDATED outcome"
                )
        else:
            _require_positive_int("worker_generation", self.worker_generation)
        _require_local_enqueue_seq("local_enqueue_seq", self.local_enqueue_seq)
        _require_non_negative_int("terminal_observed_at_monotonic_ns", self.terminal_observed_at_monotonic_ns)
        _require_aware_utc_canonicalizable("terminal_at_utc", self.terminal_at_utc)

        for field_name in (
            "provider_error_code",
            "provider_error_message",
            "diagnostic_reason",
        ):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field_name} must be a str when present")

        if not isinstance(self.command, ProviderCommand):
            raise ValueError("command must be a ProviderCommand")
        if self.command.runtime_instance_id != self.runtime_instance_id:
            raise ValueError(
                "command.runtime_instance_id must equal the outcome runtime_instance_id "
                "(no cross-context identity mixing)"
            )
        if self.command.provider_id != self.provider_id:
            raise ValueError(
                "command.provider_id must equal the outcome provider_id "
                "(no cross-context identity mixing)"
            )

        if not isinstance(self.outcome, ProviderExecutionOutcome):
            raise ValueError("outcome must be a ProviderExecutionOutcome, not a raw string")

        if self.dispatched_at_monotonic_ns is not None:
            _require_non_negative_int("dispatched_at_monotonic_ns", self.dispatched_at_monotonic_ns)
            if self.terminal_observed_at_monotonic_ns < self.dispatched_at_monotonic_ns:
                raise ValueError(
                    "terminal_observed_at_monotonic_ns must be >= dispatched_at_monotonic_ns"
                )
        elif self.outcome in _DISPATCH_REQUIRED_OUTCOMES:
            raise ValueError(
                f"outcome {self.outcome.value!r} requires a dispatched_at_monotonic_ns "
                "(only never-dispatched cancellation outcomes may omit it)"
            )

        if self.normalized_provider_payload is not None:
            if not isinstance(self.normalized_provider_payload, Mapping):
                raise ValueError("normalized_provider_payload must be a Mapping when present")
            frozen = freeze_normalized_payload(self.normalized_provider_payload)
            object.__setattr__(self, "normalized_provider_payload", frozen)


@dataclass(frozen=True)
class ProviderWorkerLifecycleEvidence:
    """One immutable worker-process lifecycle observation.

    PID/exit code are diagnostic execution facts, never provider/business
    identity (R3 §5). An old worker generation may remain historical
    evidence but cannot acquire current execution authority.
    """

    runtime_instance_id: str
    provider_id: str
    worker_generation: int
    kind: ProviderWorkerEvidenceKind
    observed_at_monotonic_ns: int
    observed_at_utc: datetime
    process_pid: int | None = None
    exit_code: int | None = None
    diagnostic_reason: str | None = None
    local_enqueue_seq: int | None = None

    def __post_init__(self) -> None:
        _require_non_blank_str("runtime_instance_id", self.runtime_instance_id)
        _require_non_blank_str("provider_id", self.provider_id)
        _require_positive_int("worker_generation", self.worker_generation)
        _require_local_enqueue_seq("local_enqueue_seq", self.local_enqueue_seq)
        _require_non_negative_int("observed_at_monotonic_ns", self.observed_at_monotonic_ns)
        _require_aware_utc_canonicalizable("observed_at_utc", self.observed_at_utc)

        if not isinstance(self.kind, ProviderWorkerEvidenceKind):
            raise ValueError("kind must be a ProviderWorkerEvidenceKind, not a raw string")

        if self.process_pid is not None:
            _require_positive_int("process_pid", self.process_pid)

        if self.exit_code is not None:
            # Exit code is diagnostic and may be negative/zero/positive per
            # platform semantics; it must still be a real int, never a bool.
            if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
                raise ValueError("exit_code must be an int when present (bool is rejected)")

        if self.diagnostic_reason is not None and not isinstance(self.diagnostic_reason, str):
            raise ValueError("diagnostic_reason must be a str when present")


@dataclass(frozen=True)
class ProviderWorkerSupervisorConfig:
    """Fully materialized, immutable supervisor configuration.

    No numeric values are frozen by the design; every field is required at
    construction (no implicit defaults). ``command_timeout_seconds`` must
    cover exactly every current ``ProviderCommandType`` member -- missing or
    extra/foreign keys fail construction (freeze §10, R3 §7.1, R4 PWS-28).
    """

    startup_timeout_seconds: float
    command_timeout_seconds: Mapping[ProviderCommandType, float]
    graceful_shutdown_timeout_seconds: float
    terminate_join_timeout_seconds: float
    kill_join_timeout_seconds: float
    parent_command_queue_capacity: int
    child_data_queue_capacity: int
    child_priority_queue_capacity: int
    supervisor_inbox_capacity: int
    max_frame_bytes: int
    protocol_version: int

    def __post_init__(self) -> None:
        # Every timeout finite and > 0.
        startup_timeout = _require_finite_positive_float(
            "startup_timeout_seconds", self.startup_timeout_seconds
        )
        graceful_shutdown_timeout = _require_finite_positive_float(
            "graceful_shutdown_timeout_seconds", self.graceful_shutdown_timeout_seconds
        )
        terminate_join_timeout = _require_finite_positive_float(
            "terminate_join_timeout_seconds", self.terminate_join_timeout_seconds
        )
        kill_join_timeout = _require_finite_positive_float(
            "kill_join_timeout_seconds", self.kill_join_timeout_seconds
        )

        # Capacities / frame / protocol: positive ints, bool rejected.
        for name in (
            "parent_command_queue_capacity",
            "child_data_queue_capacity",
            "child_priority_queue_capacity",
            "supervisor_inbox_capacity",
            "max_frame_bytes",
        ):
            _require_positive_int(name, getattr(self, name))
        if isinstance(self.protocol_version, bool) or not isinstance(self.protocol_version, int):
            raise ValueError("protocol_version must be an int (bool is rejected)")
        if self.protocol_version < 1:
            raise ValueError("protocol_version must be >= 1")

        # Exact command-timeout coverage over every current ProviderCommandType.
        if not isinstance(self.command_timeout_seconds, Mapping):
            raise ValueError("command_timeout_seconds must be a Mapping")
        command_timeouts: dict[ProviderCommandType, float] = {}
        for key, value in self.command_timeout_seconds.items():
            if isinstance(key, bool) or not isinstance(key, ProviderCommandType):
                raise ValueError(
                    "command_timeout_seconds keys must be ProviderCommandType enum instances "
                    "(raw strings/foreign keys rejected)"
                )
            command_timeouts[key] = _require_finite_positive_float(
                f"command_timeout_seconds[{key.value!r}]", value
            )
        missing = set(ProviderCommandType) - set(command_timeouts)
        if missing:
            raise ValueError(
                "command_timeout_seconds must cover every ProviderCommandType member; missing: "
                + ", ".join(sorted(member.value for member in missing))
            )
        extra = set(command_timeouts) - set(ProviderCommandType)
        if extra:
            raise ValueError(
                "command_timeout_seconds must not contain extra keys; extra: "
                + ", ".join(sorted(member.value for member in extra))
            )

        object.__setattr__(self, "startup_timeout_seconds", startup_timeout)
        object.__setattr__(self, "graceful_shutdown_timeout_seconds", graceful_shutdown_timeout)
        object.__setattr__(self, "terminate_join_timeout_seconds", terminate_join_timeout)
        object.__setattr__(self, "kill_join_timeout_seconds", kill_join_timeout)
        # Immutable/read-only storage: caller mutation cannot change config
        # after construction (R3 §7.1).
        object.__setattr__(self, "command_timeout_seconds", MappingProxyType(dict(command_timeouts)))
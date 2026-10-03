"""Provider-independent persistent worker for read-only futures observation.

The worker owns scheduling/retry/isolation only. It does not decide currentness,
continuity, delivery mode, entitlement, LiveFeed lifecycle, Radar admission, or
trading permission. Those remain downstream evidence decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol

from data_provider.futures_runtime_observation import FuturesRuntimeObserver


class FuturesFetcher(Protocol):
    def __call__(self, root: str, timeframe: str, *, observed_at_utc: datetime) -> object: ...


@dataclass(frozen=True)
class WorkerPolicy:
    roots: tuple[str, ...] = ("GC", "CL", "SI", "HG")
    timeframe: str = "5m"
    base_backoff_seconds: float = 5.0
    max_backoff_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.roots:
            raise ValueError("roots are required")
        if self.base_backoff_seconds <= 0 or self.max_backoff_seconds <= 0:
            raise ValueError("backoff must be positive")
        if self.base_backoff_seconds > self.max_backoff_seconds:
            raise ValueError("base backoff cannot exceed max backoff")


@dataclass(frozen=True)
class WorkerRootState:
    root: str
    failures: int = 0
    next_eligible_monotonic: float = 0.0
    last_attempt_utc: datetime | None = None
    last_success_utc: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True)
class WorkerCycleResult:
    attempted: tuple[str, ...]
    succeeded: tuple[str, ...]
    failed: tuple[str, ...]
    skipped_backoff: tuple[str, ...]


class FuturesPersistentWorker:
    """Deterministic worker core; caller owns process/thread isolation and timers."""

    def __init__(
        self,
        *,
        observer: FuturesRuntimeObserver,
        fetch: FuturesFetcher,
        policy: WorkerPolicy = WorkerPolicy(),
    ) -> None:
        self._observer = observer
        self._fetch = fetch
        self._policy = policy
        self._states = {root: WorkerRootState(root=root) for root in policy.roots}
        self._stopped = False

    @property
    def states(self) -> tuple[WorkerRootState, ...]:
        return tuple(self._states[root] for root in self._policy.roots)

    def stop(self) -> None:
        self._stopped = True

    def restart(self, generation: int, *, observed_at_utc: datetime) -> None:
        self._observer.rollover_generation(generation, observed_at_utc=observed_at_utc)
        self._states = {root: WorkerRootState(root=root) for root in self._policy.roots}
        self._stopped = False

    def run_cycle(
        self,
        *,
        observed_at_utc: datetime,
        monotonic_now: float,
    ) -> WorkerCycleResult:
        if self._stopped:
            return WorkerCycleResult((), (), (), self._policy.roots)
        if observed_at_utc.tzinfo is None or observed_at_utc.utcoffset() is None:
            raise ValueError("observed_at_utc must be timezone-aware")
        now = observed_at_utc.astimezone(timezone.utc)
        attempted: list[str] = []
        succeeded: list[str] = []
        failed: list[str] = []
        skipped: list[str] = []

        for root in self._policy.roots:
            state = self._states[root]
            if monotonic_now < state.next_eligible_monotonic:
                skipped.append(root)
                continue
            attempted.append(root)
            try:
                observations = self._observer.sample(
                    self._fetch,
                    root,
                    self._policy.timeframe,
                    observed_at_utc=now,
                )
                source_error = any(getattr(item, "transport_transition", None) == "ERROR" for item in observations)
                if source_error:
                    raise RuntimeError("source observation reported ERROR")
            except Exception as exc:
                failures = state.failures + 1
                delay = min(
                    self._policy.max_backoff_seconds,
                    self._policy.base_backoff_seconds * (2 ** (failures - 1)),
                )
                self._states[root] = WorkerRootState(
                    root=root,
                    failures=failures,
                    next_eligible_monotonic=monotonic_now + delay,
                    last_attempt_utc=now,
                    last_success_utc=state.last_success_utc,
                    last_error=type(exc).__name__,
                )
                failed.append(root)
                continue

            self._states[root] = WorkerRootState(
                root=root,
                failures=0,
                next_eligible_monotonic=monotonic_now,
                last_attempt_utc=now,
                last_success_utc=now,
                last_error=None,
            )
            succeeded.append(root)

        return WorkerCycleResult(tuple(attempted), tuple(succeeded), tuple(failed), tuple(skipped))

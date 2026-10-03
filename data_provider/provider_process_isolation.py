"""Killable process-isolation backend for provider calls.

This boundary owns execution containment only. Child results are opaque values;
no market-data trust, currentness, continuity, delivery mode, entitlement,
LiveFeed lifecycle, Radar admission, or trading permission is inferred here.
"""

from __future__ import annotations

import multiprocessing as mp
from dataclasses import dataclass
from queue import Empty
from typing import Callable, Generic, TypeVar

from data_provider.provider_execution_isolation import (
    IsolationPolicy,
    ProviderExecutionTimeout,
)

T = TypeVar("T")


class ProviderChildProcessError(RuntimeError):
    pass


def _child_entry(fn: Callable[[], T], queue) -> None:
    try:
        queue.put(("ok", fn()))
    except BaseException as exc:
        queue.put(("error", type(exc).__name__, str(exc)))


@dataclass(frozen=True)
class ProcessIsolationPolicy:
    timeout_seconds: float = 10.0
    cleanup_seconds: float = 1.0
    start_method: str = "spawn"

    def __post_init__(self) -> None:
        IsolationPolicy(self.timeout_seconds)
        if self.cleanup_seconds <= 0:
            raise ValueError("cleanup_seconds must be positive")
        if self.start_method not in mp.get_all_start_methods():
            raise ValueError("unsupported multiprocessing start method")


class ProcessCallExecutor(Generic[T]):
    """Execute one provider call in a disposable, killable child process."""

    def __init__(self, policy: ProcessIsolationPolicy = ProcessIsolationPolicy()) -> None:
        self._policy = policy
        self._ctx = mp.get_context(policy.start_method)

    def call(self, fn: Callable[[], T]) -> T:
        queue = self._ctx.Queue(maxsize=1)
        process = self._ctx.Process(target=_child_entry, args=(fn, queue), daemon=False)
        process.start()
        process.join(self._policy.timeout_seconds)

        if process.is_alive():
            process.terminate()
            process.join(self._policy.cleanup_seconds)
            if process.is_alive():
                process.kill()
                process.join(self._policy.cleanup_seconds)
            if process.is_alive():
                raise ProviderChildProcessError("provider child could not be terminated")
            raise ProviderExecutionTimeout(
                f"provider child exceeded {self._policy.timeout_seconds}s and was terminated"
            )

        try:
            message = queue.get_nowait()
        except Empty:
            raise ProviderChildProcessError(
                f"provider child exited without result; exitcode={process.exitcode}"
            )
        finally:
            queue.close()
            queue.join_thread()

        if message[0] == "ok":
            return message[1]
        if message[0] == "error":
            _, error_type, error_message = message
            raise ProviderChildProcessError(f"{error_type}: {error_message}")
        raise ProviderChildProcessError("provider child returned invalid result envelope")

"""Bounded execution-isolation boundary for blocking provider calls.

This module does not classify market-data quality.  It only prevents one
provider call from owning the caller indefinitely.  Production may replace the
executor implementation without changing the worker/qualification contracts.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class ProviderExecutionTimeout(TimeoutError):
    pass


@dataclass(frozen=True)
class IsolationPolicy:
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")


class BoundedCallExecutor(Generic[T]):
    """Run one call behind a bounded wait.

    A timed-out thread cannot be force-killed safely by Python; therefore this
    is an explicit containment seam, not process-kill proof.  The executor is
    replaceable by a process-isolated implementation for cloud production.
    """

    def __init__(self, policy: IsolationPolicy = IsolationPolicy()) -> None:
        self._policy = policy

    def call(self, fn: Callable[[], T]) -> T:
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="futures-provider")
        future: Future[T] = pool.submit(fn)
        try:
            return future.result(timeout=self._policy.timeout_seconds)
        except FutureTimeout as exc:
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            raise ProviderExecutionTimeout(
                f"provider call exceeded {self._policy.timeout_seconds}s"
            ) from exc
        except BaseException:
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            pool.shutdown(wait=True)

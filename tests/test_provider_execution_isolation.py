import threading
import time

import pytest

from data_provider.provider_execution_isolation import (
    BoundedCallExecutor,
    IsolationPolicy,
    ProviderExecutionTimeout,
)


def test_success_returns_value():
    executor = BoundedCallExecutor(IsolationPolicy(timeout_seconds=0.2))
    assert executor.call(lambda: 7) == 7


def test_provider_exception_propagates():
    executor = BoundedCallExecutor(IsolationPolicy(timeout_seconds=0.2))

    def fail():
        raise ValueError("provider failure")

    with pytest.raises(ValueError, match="provider failure"):
        executor.call(fail)


def test_timeout_fails_closed_without_waiting_for_blocked_call():
    release = threading.Event()
    executor = BoundedCallExecutor(IsolationPolicy(timeout_seconds=0.02))

    def block():
        release.wait(1)
        return 1

    started = time.monotonic()
    try:
        with pytest.raises(ProviderExecutionTimeout):
            executor.call(block)
        assert time.monotonic() - started < 0.5
    finally:
        release.set()


def test_timeout_policy_must_be_positive():
    with pytest.raises(ValueError):
        IsolationPolicy(timeout_seconds=0)

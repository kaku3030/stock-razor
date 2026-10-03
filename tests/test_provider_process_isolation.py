import os
import time

import pytest

from data_provider.provider_execution_isolation import ProviderExecutionTimeout
from data_provider.provider_process_isolation import (
    ProcessCallExecutor,
    ProcessIsolationPolicy,
    ProviderChildProcessError,
)


def _return_value():
    return {"value": 7}


def _raise_value_error():
    raise ValueError("provider exploded")


def _block_forever():
    while True:
        time.sleep(1)


def _hard_exit():
    os._exit(23)


def test_process_executor_returns_picklable_result():
    executor = ProcessCallExecutor(ProcessIsolationPolicy(timeout_seconds=2))
    assert executor.call(_return_value) == {"value": 7}


def test_child_exception_is_fail_closed():
    executor = ProcessCallExecutor(ProcessIsolationPolicy(timeout_seconds=2))
    with pytest.raises(ProviderChildProcessError, match="ValueError: provider exploded"):
        executor.call(_raise_value_error)


def test_timeout_terminates_child_and_returns_control():
    executor = ProcessCallExecutor(
        ProcessIsolationPolicy(timeout_seconds=0.1, cleanup_seconds=0.5)
    )
    started = time.monotonic()
    with pytest.raises(ProviderExecutionTimeout, match="was terminated"):
        executor.call(_block_forever)
    assert time.monotonic() - started < 2


def test_child_crash_without_envelope_is_fail_closed():
    executor = ProcessCallExecutor(ProcessIsolationPolicy(timeout_seconds=2))
    with pytest.raises(ProviderChildProcessError, match="exitcode=23"):
        executor.call(_hard_exit)


def test_invalid_cleanup_policy_fails_closed():
    with pytest.raises(ValueError, match="cleanup_seconds"):
        ProcessIsolationPolicy(cleanup_seconds=0)

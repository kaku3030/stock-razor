from datetime import datetime, timezone

import pytest

from data_provider.futures_persistent_worker import FuturesPersistentWorker, WorkerPolicy


class FakeObserver:
    def __init__(self):
        self.calls = []
        self.rollovers = []

    def sample(self, fetch, root, timeframe, *, observed_at_utc):
        self.calls.append((root, timeframe))
        return fetch(root, timeframe, observed_at_utc=observed_at_utc)

    def rollover_generation(self, generation, *, observed_at_utc):
        self.rollovers.append(generation)


class Observation:
    def __init__(self, transition="SAMPLE"):
        self.transport_transition = transition


NOW = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)


def test_one_root_failure_does_not_block_other_roots():
    observer = FakeObserver()

    def fetch(root, timeframe, *, observed_at_utc):
        if root == "CL":
            raise RuntimeError("source down")
        return [Observation()]

    worker = FuturesPersistentWorker(observer=observer, fetch=fetch)
    result = worker.run_cycle(observed_at_utc=NOW, monotonic_now=100.0)

    assert result.attempted == ("GC", "CL", "SI", "HG")
    assert result.succeeded == ("GC", "SI", "HG")
    assert result.failed == ("CL",)


def test_backoff_is_bounded_and_per_root():
    observer = FakeObserver()

    def fetch(root, timeframe, *, observed_at_utc):
        if root == "GC":
            raise RuntimeError("down")
        return [Observation()]

    worker = FuturesPersistentWorker(
        observer=observer,
        fetch=fetch,
        policy=WorkerPolicy(base_backoff_seconds=5, max_backoff_seconds=10),
    )
    first = worker.run_cycle(observed_at_utc=NOW, monotonic_now=0)
    second = worker.run_cycle(observed_at_utc=NOW, monotonic_now=1)
    third = worker.run_cycle(observed_at_utc=NOW, monotonic_now=5)

    assert first.failed == ("GC",)
    assert second.skipped_backoff == ("GC",)
    assert "GC" in third.failed
    gc = worker.states[0]
    assert gc.failures == 2
    assert gc.next_eligible_monotonic == 15


def test_error_observation_is_not_counted_as_success():
    observer = FakeObserver()

    def fetch(root, timeframe, *, observed_at_utc):
        return [Observation("ERROR")] if root == "GC" else [Observation()]

    worker = FuturesPersistentWorker(observer=observer, fetch=fetch)
    result = worker.run_cycle(observed_at_utc=NOW, monotonic_now=0)

    assert "GC" in result.failed
    assert "GC" not in result.succeeded


def test_restart_requires_generation_rollover_and_resets_backoff():
    observer = FakeObserver()

    def fetch(root, timeframe, *, observed_at_utc):
        raise RuntimeError("down")

    worker = FuturesPersistentWorker(observer=observer, fetch=fetch)
    worker.run_cycle(observed_at_utc=NOW, monotonic_now=0)
    assert worker.states[0].failures == 1

    worker.restart(2, observed_at_utc=NOW)

    assert observer.rollovers == [2]
    assert all(state.failures == 0 for state in worker.states)
    assert all(state.next_eligible_monotonic == 0 for state in worker.states)


def test_stop_prevents_provider_calls():
    observer = FakeObserver()

    def fetch(root, timeframe, *, observed_at_utc):
        raise AssertionError("must not be called")

    worker = FuturesPersistentWorker(observer=observer, fetch=fetch)
    worker.stop()
    result = worker.run_cycle(observed_at_utc=NOW, monotonic_now=0)

    assert result.attempted == ()
    assert result.skipped_backoff == ("GC", "CL", "SI", "HG")


def test_naive_runtime_timestamp_fails_closed():
    observer = FakeObserver()
    worker = FuturesPersistentWorker(observer=observer, fetch=lambda *args, **kwargs: [Observation()])

    with pytest.raises(ValueError, match="timezone-aware"):
        worker.run_cycle(observed_at_utc=datetime(2026, 10, 4), monotonic_now=0)

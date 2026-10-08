from threading import Thread
from time import monotonic

from src.services.live_feed.producer_wakeup import DataArrivalWake


def test_no_new_event_waits_for_bounded_health_deadline():
    wake = DataArrivalWake()
    started = monotonic()
    observed = wake.wait_when_unchanged(
        lambda: 3, last_processed_count=3, max_wait_seconds=0.015
    )
    elapsed = monotonic() - started
    assert observed is False
    assert elapsed >= 0.010
    assert elapsed < 0.5


def test_notify_short_circuits_long_health_wait():
    wake = DataArrivalWake()
    observed = []
    def runner():
        observed.append(wake.wait_when_unchanged(
            lambda: 3, last_processed_count=3, max_wait_seconds=2.0
        ))
    thread = Thread(target=runner)
    thread.start()
    wake.notify()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert observed == [True]


def test_double_check_catches_event_between_clear_and_wait():
    wake = DataArrivalWake()
    count_reads = 0
    def count():
        nonlocal count_reads
        count_reads += 1
        return 6
    # A newly arrived event is already reflected in the producer counter.
    assert wake.wait_when_unchanged(
        count, last_processed_count=5, max_wait_seconds=10.0
    ) is True
    assert count_reads == 1


def test_zero_wait_never_blocks_or_claims_callback():
    wake = DataArrivalWake()
    assert wake.wait_when_unchanged(
        lambda: 0, last_processed_count=0, max_wait_seconds=0
    ) is False

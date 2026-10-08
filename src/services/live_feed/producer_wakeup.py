"""Wake a read-only producer on accepted push callbacks without busy polling.

Only the single writer drains provider events. The callback signals an Event;
it never calls provider RPCs or computes signals. Waiting is bounded by a
separate periodic health deadline. No market event timestamps are inferred.
"""
from __future__ import annotations

from threading import Event
from typing import Callable


class DataArrivalWake:
    def __init__(self) -> None:
        self._event = Event()

    def notify(self) -> None:
        self._event.set()

    def wait_when_unchanged(
        self,
        read_event_count: Callable[[], int],
        *,
        last_processed_count: int,
        max_wait_seconds: float,
    ) -> bool:
        """Return whether a wake occurred; caller must always reread count.

        Clearing the flag before double-checking the count ensures a callback
        cannot disappear between the initial observation and the Event.wait.
        A failed or missed notification is bounded by the health deadline.
        """
        if max_wait_seconds <= 0:
            return False
        self._event.clear()
        if read_event_count() != last_processed_count:
            return True
        return self._event.wait(timeout=max_wait_seconds)

"""AI Monitor -> existing LiveFeed intent delta contract V0.1.

This module deliberately stops before the LiveFeedController mutation boundary.
It never calls a provider SDK, never creates a second subscription runtime, and
never removes another consumer's desired stream. The existing LiveFeed desired
registry is not yet consumer/source-aware, so binding these deltas to controller
requests remains blocked until shared-key ownership/reference semantics exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .watch_universe import WatchIdentity, WatchUniverseSnapshot


AI_MONITOR_LIVE_FEED_CONSUMER_ID = "AI_MONITOR_ACTIVE_WATCH"


@dataclass(frozen=True)
class WatchIntentDelta:
    consumer_id: str
    desired: tuple[WatchIdentity, ...]
    added: tuple[WatchIdentity, ...]
    removed: tuple[WatchIdentity, ...]
    unchanged: tuple[WatchIdentity, ...]


def _ordered(values: Iterable[WatchIdentity]) -> tuple[WatchIdentity, ...]:
    return tuple(sorted(values, key=lambda item: (item.market, item.symbol)))


def plan_live_feed_watch_intent(
    *,
    previous_desired: Iterable[WatchIdentity],
    snapshot: WatchUniverseSnapshot,
) -> WatchIntentDelta:
    """Compute AI Monitor's consumer-owned desired-watch delta only.

    ``previous_desired`` is the caller's last committed AI Monitor consumer
    intent, not provider subscription truth. The result is safe to audit or
    enqueue into a future source-aware LiveFeed intent boundary, but this
    function itself performs no runtime mutation.
    """

    previous = set(previous_desired)
    desired = set(snapshot.active_identities)
    return WatchIntentDelta(
        consumer_id=AI_MONITOR_LIVE_FEED_CONSUMER_ID,
        desired=_ordered(desired),
        added=_ordered(desired - previous),
        removed=_ordered(previous - desired),
        unchanged=_ordered(previous & desired),
    )

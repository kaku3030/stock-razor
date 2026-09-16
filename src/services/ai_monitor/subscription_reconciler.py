"""AI Monitor watch-to-stream subscription reconciliation V0.1.

This module translates an already-authorized Active Watch Universe snapshot into
provider subscription deltas. It does not discover candidates, own market-data
truth, grant Entry Permission, or create a second LiveFeed runtime.

Provider mutations are deliberately fail-closed: if a subscribe/unsubscribe
call has an uncertain outcome, the reconciler marks its local subscription
state UNKNOWN and refuses further mutations until the caller establishes a new
transport session and explicitly resets the reconciler.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from data_provider.market_data_adapter import BarCallback, MarketDataAdapter

from .watch_universe import WatchUniverseSnapshot


class SubscriptionKnowledge(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class SubscriptionStateUnknownError(RuntimeError):
    """Raised when provider subscription state cannot be proven exact."""


@dataclass(frozen=True)
class SubscriptionReconcileResult:
    market: str
    timeframe: str
    desired: tuple[str, ...]
    subscribed: tuple[str, ...]
    unsubscribed: tuple[str, ...]
    unchanged: tuple[str, ...]
    knowledge: SubscriptionKnowledge = SubscriptionKnowledge.KNOWN


class WatchSubscriptionReconciler:
    """Reconcile one market's desired watch set against one stream transport.

    The instance is scoped to one concrete stream session. After transport
    restart, call ``reset_after_transport_restart`` only when the new session is
    known to start with zero subscriptions; the next reconcile then subscribes
    the full desired universe.
    """

    def __init__(
        self,
        adapter: MarketDataAdapter,
        *,
        market: str,
        callback: BarCallback,
        timeframe: str = "1m",
    ) -> None:
        normalized_market = str(market or "").strip().lower()
        if not normalized_market:
            raise ValueError("market must not be empty")
        if callback is None:
            raise ValueError("callback is required")
        self._adapter = adapter
        self._market = normalized_market
        self._callback = callback
        self._timeframe = str(timeframe or "").strip()
        if not self._timeframe:
            raise ValueError("timeframe must not be empty")
        self._known_subscriptions: set[str] = set()
        self._knowledge = SubscriptionKnowledge.KNOWN

    @property
    def knowledge(self) -> SubscriptionKnowledge:
        return self._knowledge

    @property
    def known_subscriptions(self) -> tuple[str, ...]:
        return tuple(sorted(self._known_subscriptions))

    def reset_after_transport_restart(self) -> None:
        """Bind to a proven-empty new stream session after restart/reconnect."""

        self._known_subscriptions.clear()
        self._knowledge = SubscriptionKnowledge.KNOWN

    def reconcile(self, snapshot: WatchUniverseSnapshot) -> SubscriptionReconcileResult:
        if self._knowledge is SubscriptionKnowledge.UNKNOWN:
            raise SubscriptionStateUnknownError(
                "subscription state is UNKNOWN; restart transport before reconciling"
            )

        desired = {
            identity.symbol
            for identity in snapshot.active_identities
            if identity.market == self._market
        }
        to_subscribe = desired - self._known_subscriptions
        to_unsubscribe = self._known_subscriptions - desired
        unchanged = desired & self._known_subscriptions

        subscribe_codes = tuple(sorted(to_subscribe))
        unsubscribe_codes = tuple(sorted(to_unsubscribe))
        try:
            # Preserve monitoring coverage: establish additions before releasing
            # symbols that are no longer desired.
            if subscribe_codes:
                self._adapter.subscribe(
                    subscribe_codes,
                    timeframe=self._timeframe,
                    callback=self._callback,
                )
            if unsubscribe_codes:
                self._adapter.unsubscribe(
                    unsubscribe_codes,
                    timeframe=self._timeframe,
                )
        except Exception as exc:
            # A provider call may have partially applied. Never guess the
            # resulting subscription set or blindly retry on the same session.
            self._knowledge = SubscriptionKnowledge.UNKNOWN
            raise SubscriptionStateUnknownError(
                "provider subscription mutation outcome is uncertain"
            ) from exc

        self._known_subscriptions = desired
        return SubscriptionReconcileResult(
            market=self._market,
            timeframe=self._timeframe,
            desired=tuple(sorted(desired)),
            subscribed=subscribe_codes,
            unsubscribed=unsubscribe_codes,
            unchanged=tuple(sorted(unchanged)),
        )
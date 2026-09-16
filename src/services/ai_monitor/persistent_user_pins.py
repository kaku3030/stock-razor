"""Bridge durable USER_PINNED truth into Active Watch Universe state."""

from __future__ import annotations

from datetime import datetime, timezone

from src.repositories.ai_monitor_user_pin_repo import AIMonitorUserPinRepository

from .watch_universe import ActiveWatchUniverse, WatchIdentity, WatchSource, WatchUniverseSnapshot


class PersistentUserPins:
    """Keep one owner's explicit pins durable across process restarts.

    Persistence is authoritative for USER_PINNED membership only. Portfolio and
    Radar membership remain owned by their existing sources and are never
    changed by this service.
    """

    def __init__(
        self,
        repository: AIMonitorUserPinRepository,
        universe: ActiveWatchUniverse,
        *,
        owner_id: str,
    ) -> None:
        self._repository = repository
        self._universe = universe
        self._owner_id = str(owner_id or "").strip()
        if not self._owner_id:
            raise ValueError("owner_id must not be empty")

    def hydrate(self, *, generated_at: datetime | None = None) -> WatchUniverseSnapshot:
        """Reconcile in-memory USER_PINNED membership to durable truth."""

        pins = self._repository.list_pins(owner_id=self._owner_id)
        durable = {WatchIdentity(pin.market, pin.symbol): pin for pin in pins}

        current = self._universe.snapshot(generated_at=generated_at or datetime.now(timezone.utc))
        for item in current.active_items:
            if WatchSource.USER_PINNED in item.sources and item.identity not in durable:
                self._universe.unpin(
                    market=item.identity.market,
                    symbol=item.identity.symbol,
                )

        for identity, pin in durable.items():
            self._universe.pin(
                market=identity.market,
                symbol=identity.symbol,
                activated_at=pin.pinned_at,
            )

        return self._universe.snapshot(generated_at=generated_at or datetime.now(timezone.utc))

    def pin(
        self,
        *,
        market: str,
        symbol: str,
        pinned_at: datetime | None = None,
    ) -> WatchUniverseSnapshot:
        persisted = self._repository.pin(
            owner_id=self._owner_id,
            market=market,
            symbol=symbol,
            pinned_at=pinned_at,
        )
        self._universe.pin(
            market=persisted.market,
            symbol=persisted.symbol,
            activated_at=persisted.pinned_at,
        )
        return self._universe.snapshot()

    def unpin(self, *, market: str, symbol: str) -> WatchUniverseSnapshot:
        self._repository.unpin(
            owner_id=self._owner_id,
            market=market,
            symbol=symbol,
        )
        # Reconcile memory even when the durable row was already absent.
        self._universe.unpin(market=market, symbol=symbol)
        return self._universe.snapshot()

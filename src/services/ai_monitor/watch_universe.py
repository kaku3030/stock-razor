"""AI Monitor Active Watch Universe V0.1.

This module is deliberately a small ownership-boundary contract. It decides
which symbols AI Monitor should keep observing; it does not discover candidates,
fetch market data, interpret structure, grant entry permission, or place orders.

The active universe is the union of portfolio positions, Radar-promoted
candidates, and user-pinned symbols. A symbol remains active while at least one
source remains. Source removal is source-local, so closing a position never
removes a Radar/user watch and Radar expiry never removes a user pin.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Mapping, Optional


class WatchSource(str, Enum):
    PORTFOLIO = "PORTFOLIO"
    RADAR = "RADAR"
    USER_PINNED = "USER_PINNED"


class WatchLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    WATCH_EXPIRED = "WATCH_EXPIRED"
    ARCHIVED = "ARCHIVED"


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        raise ValueError("symbol must not be empty")
    return normalized


def _normalize_market(market: str) -> str:
    normalized = str(market or "").strip().lower()
    if not normalized:
        raise ValueError("market must not be empty")
    return normalized


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, order=True)
class WatchIdentity:
    market: str
    symbol: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "market", _normalize_market(self.market))
        object.__setattr__(self, "symbol", _normalize_symbol(self.symbol))


@dataclass(frozen=True)
class RadarWatchContext:
    """Radar-owned reasons copied into AI Monitor as opaque watch context."""

    candidate_id: Optional[str] = None
    candidate_status: Optional[str] = None
    watch_reason: Optional[str] = None
    lifecycle: Optional[str] = None
    key_levels: tuple[str, ...] = ()
    entry_conditions: tuple[str, ...] = ()
    invalidation_conditions: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class WatchSourceState:
    source: WatchSource
    activated_at: datetime
    radar: Optional[RadarWatchContext] = None

    def __post_init__(self) -> None:
        if self.activated_at.tzinfo is None:
            raise ValueError("activated_at must be timezone-aware")
        if self.source is not WatchSource.RADAR and self.radar is not None:
            raise ValueError("radar context is only valid for RADAR source")


@dataclass(frozen=True)
class ActiveWatch:
    identity: WatchIdentity
    sources: tuple[WatchSourceState, ...]
    lifecycle: WatchLifecycle = WatchLifecycle.ACTIVE

    @property
    def is_active(self) -> bool:
        return self.lifecycle is WatchLifecycle.ACTIVE and bool(self.sources)

    @property
    def source_names(self) -> tuple[str, ...]:
        return tuple(source.source.value for source in self.sources)


@dataclass(frozen=True)
class WatchUniverseSnapshot:
    """Immutable snapshot consumed by the AI Monitor runtime."""

    generated_at: datetime
    watches: tuple[ActiveWatch, ...]

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware")

    @property
    def active_identities(self) -> tuple[WatchIdentity, ...]:
        return tuple(watch.identity for watch in self.watches if watch.is_active)

    @property
    def active_symbols(self) -> tuple[str, ...]:
        return tuple(identity.symbol for identity in self.active_identities)


class ActiveWatchUniverse:
    """Deterministic source-union state for AI Monitor subscriptions.

    This object owns watch membership only. Persistence, provider subscription,
    market-data truth, Radar discovery, Entry Permission, and execution remain
    outside this contract.
    """

    def __init__(self) -> None:
        self._sources: dict[WatchIdentity, dict[WatchSource, WatchSourceState]] = {}
        self._terminal: dict[WatchIdentity, WatchLifecycle] = {}

    def activate(
        self,
        *,
        market: str,
        symbol: str,
        source: WatchSource,
        activated_at: Optional[datetime] = None,
        radar: Optional[RadarWatchContext] = None,
    ) -> ActiveWatch:
        identity = WatchIdentity(market=market, symbol=symbol)
        timestamp = activated_at or _utc_now()
        state = WatchSourceState(source=source, activated_at=timestamp, radar=radar)
        self._sources.setdefault(identity, {})[source] = state
        self._terminal.pop(identity, None)
        return self.get(identity)

    def remove_source(
        self,
        *,
        market: str,
        symbol: str,
        source: WatchSource,
        lifecycle_if_empty: WatchLifecycle = WatchLifecycle.WATCH_EXPIRED,
    ) -> ActiveWatch:
        if lifecycle_if_empty is WatchLifecycle.ACTIVE:
            raise ValueError("empty watch cannot remain ACTIVE")
        identity = WatchIdentity(market=market, symbol=symbol)
        states = self._sources.get(identity, {})
        states.pop(source, None)
        if states:
            return self.get(identity)
        self._sources.pop(identity, None)
        self._terminal[identity] = lifecycle_if_empty
        return self.get(identity)

    def archive(self, *, market: str, symbol: str) -> ActiveWatch:
        identity = WatchIdentity(market=market, symbol=symbol)
        self._sources.pop(identity, None)
        self._terminal[identity] = WatchLifecycle.ARCHIVED
        return self.get(identity)

    def get(self, identity: WatchIdentity) -> ActiveWatch:
        states = self._sources.get(identity, {})
        ordered = tuple(states[source] for source in WatchSource if source in states)
        lifecycle = WatchLifecycle.ACTIVE if ordered else self._terminal.get(
            identity, WatchLifecycle.WATCH_EXPIRED
        )
        return ActiveWatch(identity=identity, sources=ordered, lifecycle=lifecycle)

    def snapshot(self, *, generated_at: Optional[datetime] = None) -> WatchUniverseSnapshot:
        timestamp = generated_at or _utc_now()
        identities = sorted(set(self._sources) | set(self._terminal))
        watches = tuple(self.get(identity) for identity in identities)
        return WatchUniverseSnapshot(generated_at=timestamp, watches=watches)

    def replace_portfolio(
        self,
        identities: Iterable[WatchIdentity],
        *,
        activated_at: Optional[datetime] = None,
    ) -> WatchUniverseSnapshot:
        """Reconcile only PORTFOLIO membership; preserve Radar and user pins."""

        desired = set(identities)
        current = {
            identity
            for identity, states in self._sources.items()
            if WatchSource.PORTFOLIO in states
        }
        for identity in current - desired:
            self.remove_source(
                market=identity.market,
                symbol=identity.symbol,
                source=WatchSource.PORTFOLIO,
            )
        for identity in desired:
            if identity not in current:
                self.activate(
                    market=identity.market,
                    symbol=identity.symbol,
                    source=WatchSource.PORTFOLIO,
                    activated_at=activated_at,
                )
        return self.snapshot(generated_at=activated_at)

    def replace_radar(
        self,
        promoted: Mapping[WatchIdentity, RadarWatchContext],
        *,
        activated_at: Optional[datetime] = None,
    ) -> WatchUniverseSnapshot:
        """Reconcile only RADAR membership; preserve portfolio and user pins."""

        desired = set(promoted)
        current = {
            identity
            for identity, states in self._sources.items()
            if WatchSource.RADAR in states
        }
        for identity in current - desired:
            self.remove_source(
                market=identity.market,
                symbol=identity.symbol,
                source=WatchSource.RADAR,
            )
        for identity, context in promoted.items():
            existing = self._sources.get(identity, {}).get(WatchSource.RADAR)
            if existing is None or existing.radar != context:
                self.activate(
                    market=identity.market,
                    symbol=identity.symbol,
                    source=WatchSource.RADAR,
                    activated_at=activated_at,
                    radar=context,
                )
        return self.snapshot(generated_at=activated_at)

    def pin(
        self,
        *,
        market: str,
        symbol: str,
        activated_at: Optional[datetime] = None,
    ) -> ActiveWatch:
        return self.activate(
            market=market,
            symbol=symbol,
            source=WatchSource.USER_PINNED,
            activated_at=activated_at,
        )

    def unpin(self, *, market: str, symbol: str) -> ActiveWatch:
        return self.remove_source(
            market=market,
            symbol=symbol,
            source=WatchSource.USER_PINNED,
        )

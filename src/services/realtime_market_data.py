# -*- coding: utf-8 -*-
"""Read-only realtime market-data cache and multi-timeframe snapshot service."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Callable, Optional, Sequence

from data_provider.market_bar_builder import aggregate_bars
from data_provider.market_data_adapter import (
    Bar,
    MarketDataAdapter,
    MarketDataHealth,
    SignalPermission,
)


ACTIVE_SESSIONS = {"premarket", "regular", "afterhours", "overnight"}


@dataclass(frozen=True)
class MarketDataSnapshot:
    symbol: str
    as_of: datetime
    minute_bars: tuple[Bar, ...]
    bars_15m: tuple[Bar, ...]
    bars_1h: tuple[Bar, ...]
    health: MarketDataHealth
    provider: Optional[str]
    feed: Optional[str]
    fallback_from: Optional[str]
    fallback_reason: Optional[str]


def _stale_health(health: MarketDataHealth) -> MarketDataHealth:
    flags = tuple(dict.fromkeys((*health.quality_flags, "STALE")))
    if health.signal_permission in {SignalPermission.BLOCKED, SignalPermission.RECORD_ONLY}:
        return replace(health, quality_flags=flags)
    return MarketDataHealth(
        score=min(health.score, 79),
        grade=type(health.grade).DEGRADED,
        signal_permission=SignalPermission.WATCH_ONLY,
        quality_flags=flags,
    )


class RealtimeMarketDataService:
    """Own recent normalized 1m facts; never interpret them as trade signals."""

    def __init__(
        self,
        adapter: MarketDataAdapter,
        *,
        max_minutes: int = 480,
        freshness_limit_seconds: int = 120,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if max_minutes < 60:
            raise ValueError("max_minutes must be at least 60")
        if freshness_limit_seconds <= 0:
            raise ValueError("freshness_limit_seconds must be positive")
        self._adapter = adapter
        self._max_minutes = max_minutes
        self._freshness_limit_seconds = freshness_limit_seconds
        self._now = now
        self._bars: dict[str, dict[datetime, Bar]] = {}
        self._lock = RLock()

    def ingest(self, bar: Bar) -> bool:
        """Insert or replace a 1m fact; return whether cache state changed."""
        if bar.timeframe != "1m":
            raise ValueError("realtime cache accepts normalized 1m bars only")
        symbol = bar.symbol.upper()
        with self._lock:
            symbol_bars = self._bars.setdefault(symbol, {})
            existing = symbol_bars.get(bar.bar_start)
            if existing is not None and existing.received_at > bar.received_at:
                return False
            if existing == bar:
                return False
            symbol_bars[bar.bar_start] = bar
            if len(symbol_bars) > self._max_minutes:
                for timestamp in sorted(symbol_bars)[: len(symbol_bars) - self._max_minutes]:
                    del symbol_bars[timestamp]
            return True

    def seed(
        self,
        symbol: str,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> int:
        bars = self._adapter.get_bars(
            symbol,
            "1m",
            start=start,
            end=end,
            limit=limit or self._max_minutes,
        )
        return sum(1 for bar in bars if self.ingest(bar))

    def subscribe(
        self,
        symbols: Sequence[str],
        *,
        observer: Optional[Callable[[Bar], None]] = None,
    ) -> None:
        def on_bar(bar: Bar) -> None:
            changed = self.ingest(bar)
            if changed and observer is not None:
                observer(bar)

        self._adapter.subscribe(symbols, timeframe="1m", callback=on_bar)

    def minute_bars(self, symbol: str) -> tuple[Bar, ...]:
        with self._lock:
            return tuple(sorted(self._bars.get(symbol.upper(), {}).values(), key=lambda item: item.bar_start))

    def snapshot(self, symbol: str, *, as_of: Optional[datetime] = None) -> MarketDataSnapshot:
        effective_as_of = as_of or self._now()
        minute_bars = self.minute_bars(symbol)
        if not minute_bars:
            health = self._adapter.get_provider_health()
            return MarketDataSnapshot(
                symbol=symbol.upper(),
                as_of=effective_as_of,
                minute_bars=(),
                bars_15m=(),
                bars_1h=(),
                health=health,
                provider=None,
                feed=None,
                fallback_from=None,
                fallback_reason=None,
            )

        latest = minute_bars[-1]
        health = latest.health or self._adapter.get_provider_health()
        session = self._adapter.get_session_status(latest.market)
        age_seconds = max(0, (effective_as_of - latest.bar_end.astimezone(effective_as_of.tzinfo)).total_seconds())
        if session in ACTIVE_SESSIONS and age_seconds > self._freshness_limit_seconds:
            health = _stale_health(health)
            latest = replace(
                latest,
                health=health,
                quality_flags=tuple(dict.fromkeys((*latest.quality_flags, "STALE"))),
            )
            # Never mutate the owner cache on a read. Aggregate from this
            # local evidence snapshot *after* freshness is classified, so a
            # complete 15m/60m grid cannot launder an expired source minute.
            minute_bars = (*minute_bars[:-1], latest)

        bars_15m = tuple(aggregate_bars(list(minute_bars), "15m", as_of=effective_as_of))
        bars_1h = tuple(aggregate_bars(list(minute_bars), "1h", as_of=effective_as_of))
        return MarketDataSnapshot(
            symbol=symbol.upper(),
            as_of=effective_as_of,
            minute_bars=minute_bars,
            bars_15m=bars_15m,
            bars_1h=bars_1h,
            health=health,
            provider=latest.provider,
            feed=latest.feed,
            fallback_from=latest.fallback_from,
            fallback_reason=latest.fallback_reason,
        )


class RealtimeMarketRuntimeOwner:
    """Own exactly one realtime service for one isolated runtime lifecycle.

    The provider is deliberately supplied by the caller.  This owner never
    discovers credentials, constructs a provider, or creates a replacement
    runtime when ``start`` is called more than once.
    """

    def __init__(
        self,
        provider_factory: Callable[[], Optional[MarketDataAdapter]],
        symbols: Sequence[str],
        *,
        service_kwargs: Optional[dict] = None,
    ) -> None:
        normalized_symbols = tuple(
            dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip())
        )
        if not normalized_symbols:
            raise ValueError("at least one runtime symbol is required")
        self._provider_factory = provider_factory
        self._symbols = normalized_symbols
        self._service_kwargs = dict(service_kwargs or {})
        self._provider: Optional[MarketDataAdapter] = None
        self._service: Optional[RealtimeMarketDataService] = None
        self._lock = RLock()

    @property
    def service(self) -> Optional[RealtimeMarketDataService]:
        with self._lock:
            return self._service

    def start(self) -> RealtimeMarketDataService:
        with self._lock:
            if self._service is not None:
                return self._service

            provider = self._provider_factory()
            if provider is None:
                raise RuntimeError("realtime market-data provider is unavailable")

            service = RealtimeMarketDataService(provider, **self._service_kwargs)
            try:
                service.subscribe(self._symbols)
            except Exception:
                self._close_provider(provider)
                raise
            self._provider = provider
            self._service = service
            return service

    def stop(self) -> None:
        with self._lock:
            provider = self._provider
            if provider is not None:
                self._close_provider(provider)
            self._provider = None
            self._service = None

    def restart(self) -> RealtimeMarketDataService:
        self.stop()
        return self.start()

    @staticmethod
    def _close_provider(provider: MarketDataAdapter) -> None:
        close = getattr(provider, "close", None)
        if callable(close):
            close()

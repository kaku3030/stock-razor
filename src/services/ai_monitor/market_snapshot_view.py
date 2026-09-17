"""Non-owning, read-only projection of AI Monitor's existing normalized cache.

This view cannot construct an adapter, start a provider, seed history, subscribe,
or infer market-data entitlement. The application owner must inject an already
running RealtimeMarketDataService or its authoritative lifecycle owner;
absent evidence remains unavailable/UNKNOWN.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.realtime_market_data import RealtimeMarketDataService, RealtimeMarketRuntimeOwner


class MarketSnapshotView:
    """Expose the current existing owner's snapshots to the authenticated read API."""

    def __init__(self, owner: RealtimeMarketDataService | RealtimeMarketRuntimeOwner) -> None:
        if owner is None or not (
            callable(getattr(owner, "snapshot", None))
            or isinstance(owner, self._runtime_owner_type())
        ):
            raise ValueError("existing normalized snapshot owner required")
        self._owner = owner

    @staticmethod
    def _runtime_owner_type():
        from src.services.realtime_market_data import RealtimeMarketRuntimeOwner
        return RealtimeMarketRuntimeOwner

    @staticmethod
    def _age_ms(source: datetime, received: datetime) -> int | None:
        if (source.tzinfo is None or source.utcoffset() is None
                or received.tzinfo is None or received.utcoffset() is None):
            return None
        difference = (received - source).total_seconds() * 1000
        return max(0, round(difference)) if difference >= 0 else None

    @classmethod
    def _bar(cls, item: object) -> dict:
        return {
            "timeframe": getattr(item, "timeframe"),
            "bar_start": getattr(item, "bar_start"),
            "bar_end": getattr(item, "bar_end"),
            "open": getattr(item, "open"),
            "high": getattr(item, "high"),
            "low": getattr(item, "low"),
            "close": getattr(item, "close"),
            "volume": getattr(item, "volume"),
            "source_timestamp": getattr(item, "source_timestamp"),
            "received_at": getattr(item, "received_at"),
            "is_closed": getattr(item, "is_closed"),
            "is_complete": getattr(item, "is_complete"),
            "observed_latency_ms": cls._age_ms(
                getattr(item, "source_timestamp"), getattr(item, "received_at")
            ),
            "quality_flags": tuple(getattr(item, "quality_flags", ())),
        }

    def get_snapshot(self, symbol: str) -> dict | None:
        """Read once from the current generation; never seed or subscribe."""
        normalized = str(symbol).strip().upper()
        if not normalized:
            return None
        lifecycle = self._owner if isinstance(self._owner, self._runtime_owner_type()) else None
        service = lifecycle.service if lifecycle is not None else self._owner
        if service is None:
            return None
        snapshot = service.snapshot(normalized)
        # A stop/restart can retire the service while its snapshot is being read.
        if lifecycle is not None and lifecycle.service is not service:
            return None
        if not snapshot.minute_bars or not snapshot.provider or not snapshot.feed:
            return None
        latest = snapshot.minute_bars[-1]
        if latest.symbol.upper() != normalized or latest.market not in {"cn", "us"}:
            return None
        if (latest.provider != snapshot.provider or latest.feed != snapshot.feed):
            return None
        selected = (
            latest,
            *(items[-1] for items in (snapshot.bars_15m, snapshot.bars_1h) if items),
        )
        flags = tuple(dict.fromkeys((
            *snapshot.health.quality_flags,
            *latest.quality_flags,
            *(flag for bar in selected for flag in bar.quality_flags),
        )))
        if any((bar.provider, bar.feed, bar.market, bar.symbol.upper()) !=
               (snapshot.provider, snapshot.feed, latest.market, normalized)
               for bar in selected):
            return None
        if any(self._age_ms(bar.source_timestamp, bar.received_at) is None for bar in selected):
            flags = tuple(dict.fromkeys((*flags, "TIMESTAMP_MISMATCH")))
        delivery_mode = (
            "STALE" if "STALE" in flags else
            "DELAYED" if "DELAYED_FEED" in flags else "UNKNOWN"
        )
        # A price derived from a minute bar uses that minute's timestamp. Never
        # pretend it is an independently observed BBO or a live trade quote.
        quote_flags = tuple(dict.fromkeys((*latest.quality_flags, "BAR_DERIVED_PRICE")))
        result = {
            "symbol": normalized,
            "market": latest.market,
            "provider": snapshot.provider,
            "feed": snapshot.feed,
            "queried_at": snapshot.as_of,
            "delivery_mode": delivery_mode,
            "entitlement": "UNKNOWN",
            "health_grade": snapshot.health.grade.value,
            "quality_flags": flags,
            "quote": {
                "price": latest.close,
                "source_timestamp": latest.source_timestamp,
                "received_at": latest.received_at,
                "observed_latency_ms": self._age_ms(latest.source_timestamp, latest.received_at),
                "quality_flags": quote_flags,
            },
            "bars": tuple(self._bar(bar) for bar in selected),
        }
        return None if lifecycle is not None and lifecycle.service is not service else result

# -*- coding: utf-8 -*-
"""Point-in-time, read-only snapshot response; no provider/runtime authority."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


DeliveryMode = Literal["REALTIME", "DELAYED", "STALE", "UNKNOWN"]
Entitlement = Literal["VERIFIED", "DENIED", "UNKNOWN"]
HealthGrade = Literal["excellent", "healthy", "degraded", "unstable", "invalid", "UNKNOWN"]


class SnapshotQuote(BaseModel):
    """Price time belongs to the price's own source fact, not a newer BBO."""

    price: float
    source_timestamp: datetime
    received_at: datetime
    bid: float | None = None
    ask: float | None = None
    bid_ask_source_timestamp: datetime | None = None
    observed_latency_ms: int | None = Field(default=None, ge=0)
    quality_flags: tuple[str, ...] = ()

    @field_validator("source_timestamp", "received_at", "bid_ask_source_timestamp")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("market fact timestamps must be timezone-aware")
        return value


class SnapshotBar(BaseModel):
    timeframe: Literal["1m", "15m", "60m", "1h", "1d"]
    bar_start: datetime
    bar_end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(ge=0)
    source_timestamp: datetime
    received_at: datetime
    is_closed: bool
    is_complete: bool
    observed_latency_ms: int | None = Field(default=None, ge=0)
    quality_flags: tuple[str, ...] = ()

    @field_validator("bar_start", "bar_end", "source_timestamp", "received_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("market fact timestamps must be timezone-aware")
        return value


class MarketSnapshotResponse(BaseModel):
    """Only accepted from the existing AI Monitor-owned read-only service.

    UNKNOWN is the default for unproven delivery and entitlement. Feed/source
    identity, capture time and per-bar closure/quality are required evidence.
    """

    symbol: str = Field(min_length=1)
    market: Literal["us", "cn"]
    provider: str = Field(min_length=1)
    feed: str = Field(min_length=1)
    queried_at: datetime
    delivery_mode: DeliveryMode = "UNKNOWN"
    entitlement: Entitlement = "UNKNOWN"
    health_grade: HealthGrade = "UNKNOWN"
    quality_flags: tuple[str, ...] = ()
    quote: SnapshotQuote | None = None
    bars: tuple[SnapshotBar, ...] = ()

    @field_validator("queried_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("market fact timestamps must be timezone-aware")
        return value

# -*- coding: utf-8 -*-
"""Provider-neutral market data contracts for the realtime research radar.

This module contains no provider SDK calls and no trading/execution behavior.
Providers normalize their output into these point-in-time facts before the
feature and signal layers consume them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, Sequence


class HealthGrade(str, Enum):
    EXCELLENT = "excellent"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNSTABLE = "unstable"
    INVALID = "invalid"


class SignalPermission(str, Enum):
    NORMAL = "normal"
    WATCH_ONLY = "watch_only"
    RECORD_ONLY = "record_only"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class MarketDataHealth:
    score: int
    grade: HealthGrade
    signal_permission: SignalPermission
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Bar:
    symbol: str
    market: str
    asset_type: str
    timeframe: str
    bar_start: datetime
    bar_end: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    provider: str
    source_timestamp: datetime
    received_at: datetime
    session: str
    is_closed: bool
    is_complete: bool
    amount: Optional[float] = None
    vwap: Optional[float] = None
    feed: Optional[str] = None
    fallback_from: Optional[str] = None
    fallback_reason: Optional[str] = None
    latency_ms: int = 0
    freshness_ms: int = 0
    health: Optional[MarketDataHealth] = None
    quality_flags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Quote:
    symbol: str
    market: str
    asset_type: str
    price: float
    provider: str
    source_timestamp: datetime
    received_at: datetime
    session: str
    feed: Optional[str] = None
    fallback_from: Optional[str] = None
    fallback_reason: Optional[str] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    health: Optional[MarketDataHealth] = None
    quality_flags: tuple[str, ...] = field(default_factory=tuple)


def evaluate_health(
    *,
    freshness: float,
    completeness: float,
    timestamp: float,
    provider: float,
    continuity: float,
    cross_check: float,
    quality_flags: Sequence[str] = (),
) -> MarketDataHealth:
    """Return the deterministic V1 health gate result.

    Component inputs are normalized ratios in the inclusive range [0, 1].
    Severe fact-integrity flags always block downstream signal evaluation.
    """

    components = {
        "freshness": freshness,
        "completeness": completeness,
        "timestamp": timestamp,
        "provider": provider,
        "continuity": continuity,
        "cross_check": cross_check,
    }
    for name, value in components.items():
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1")

    flags = tuple(dict.fromkeys(str(flag).strip().upper() for flag in quality_flags if str(flag).strip()))
    severe_flags = {"INVALID_OHLC", "NON_POSITIVE_PRICE", "NEGATIVE_VOLUME", "TIMESTAMP_MISMATCH"}
    degraded_flags = {"MISSING_BAR", "MISSING_SOURCE_TIMESTAMP", "PARTIAL_BAR", "STALE"}
    score = round(
        freshness * 25
        + completeness * 20
        + timestamp * 20
        + provider * 15
        + continuity * 10
        + cross_check * 10
    )
    if severe_flags.intersection(flags):
        score = min(score, 49)
    elif degraded_flags.intersection(flags):
        score = min(score, 79)

    if score >= 90:
        grade, permission = HealthGrade.EXCELLENT, SignalPermission.NORMAL
    elif score >= 80:
        grade, permission = HealthGrade.HEALTHY, SignalPermission.NORMAL
    elif score >= 70:
        grade, permission = HealthGrade.DEGRADED, SignalPermission.WATCH_ONLY
    elif score >= 50:
        grade, permission = HealthGrade.UNSTABLE, SignalPermission.RECORD_ONLY
    else:
        grade, permission = HealthGrade.INVALID, SignalPermission.BLOCKED

    return MarketDataHealth(score=score, grade=grade, signal_permission=permission, quality_flags=flags)


BarCallback = Callable[[Bar], None]


class MarketDataAdapter(ABC):
    """Minimal provider interface consumed by the research radar."""

    @abstractmethod
    def get_latest_quote(self, symbol: str) -> Quote:
        raise NotImplementedError

    @abstractmethod
    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> list[Bar]:
        raise NotImplementedError

    @abstractmethod
    def subscribe(
        self,
        symbols: Sequence[str],
        timeframe: str = "1m",
        callback: Optional[BarCallback] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_session_status(self, market: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_provider_health(self) -> MarketDataHealth:
        raise NotImplementedError

    @abstractmethod
    def reconnect(self) -> bool:
        raise NotImplementedError

"""A-share intraday identity and provider-semantic fact contracts.

Harvest A1 scope only.

This module deliberately separates three concerns:
1. canonical market/session identity;
2. provider-observed semantic facts;
3. deterministic readiness to derive later gates.

It does NOT implement positive Currentness, Continuity, routing, provider I/O,
strategy, AI, or trading behavior. A same-date observation is never enough to
prove intraday currentness here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping
from zoneinfo import ZoneInfo

from src.services.a_share_provider_lineage import CN_REALTIME_SOURCE_LINEAGE


CN_MARKET_TIMEZONE = "Asia/Shanghai"
CN_TRADING_CALENDAR_ID = "CN_A_SHARE"
CN_REGULAR_SESSION_SEGMENTS = (("09:30", "11:30"), ("13:00", "15:00"))
_SUPPORTED_INTERVAL_MINUTES = frozenset({15, 60})


# A1 owns only the intraday provider-surface extension. Provider/upstream
# identity remains authoritative in PR #40 CN_REALTIME_SOURCE_LINEAGE.
_CN_INTRADAY_ENDPOINT_EXTENSIONS_MUTABLE = {
    "akshare_em": frozenset({"akshare.eastmoney_intraday"}),
}

for _source_token in _CN_INTRADAY_ENDPOINT_EXTENSIONS_MUTABLE:
    if _source_token not in CN_REALTIME_SOURCE_LINEAGE:
        raise RuntimeError(
            "intraday endpoint extension must reference an authoritative CN realtime source"
        )

CN_INTRADAY_ENDPOINT_EXTENSIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    _CN_INTRADAY_ENDPOINT_EXTENSIONS_MUTABLE
)


class TimestampSemantic(str, Enum):
    BAR_START = "BAR_START"
    BAR_END = "BAR_END"
    UNKNOWN = "UNKNOWN"


class ObservationReadiness(str, Enum):
    READY_FOR_DERIVED_GATES = "READY_FOR_DERIVED_GATES"
    UNKNOWN_SOURCE_IDENTITY = "UNKNOWN_SOURCE_IDENTITY"
    INVALID_INTRADAY_ENDPOINT_BINDING = "INVALID_INTRADAY_ENDPOINT_BINDING"
    UNKNOWN_TIMESTAMP_SEMANTIC = "UNKNOWN_TIMESTAMP_SEMANTIC"
    MISSING_PROVIDER_TIMESTAMP = "MISSING_PROVIDER_TIMESTAMP"
    NAIVE_PROVIDER_TIMESTAMP = "NAIVE_PROVIDER_TIMESTAMP"
    FUTURE_PROVIDER_TIMESTAMP = "FUTURE_PROVIDER_TIMESTAMP"
    FUTURE_OBSERVATION_TIME = "FUTURE_OBSERVATION_TIME"
    PROVIDER_TIMESTAMP_AFTER_OBSERVED_AT = "PROVIDER_TIMESTAMP_AFTER_OBSERVED_AT"
    PROVIDER_OBSERVATION_INCOMPLETE = "PROVIDER_OBSERVATION_INCOMPLETE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"


@dataclass(frozen=True)
class CanonicalIntradayIdentity:
    """Provider-neutral identity for one A-share intraday bar stream."""

    market: str
    exchange: str
    instrument_id: str
    symbol: str
    trading_calendar_id: str
    timezone_name: str
    session_segments: tuple[tuple[str, str], ...]
    interval_minutes: int
    adjustment_mode: str

    def __post_init__(self) -> None:
        for field_name in (
            "market",
            "exchange",
            "instrument_id",
            "symbol",
            "trading_calendar_id",
            "timezone_name",
            "adjustment_mode",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{field_name} must be a non-empty trimmed string")

        if self.market != "cn":
            raise ValueError("A-share intraday identity requires market='cn'")
        if self.trading_calendar_id != CN_TRADING_CALENDAR_ID:
            raise ValueError(f"A-share trading calendar must be {CN_TRADING_CALENDAR_ID}")
        if self.timezone_name != CN_MARKET_TIMEZONE:
            raise ValueError(f"A-share market timezone must be {CN_MARKET_TIMEZONE}")
        if self.session_segments != CN_REGULAR_SESSION_SEGMENTS:
            raise ValueError("session_segments must match the canonical regular A-share session")
        if self.interval_minutes not in _SUPPORTED_INTERVAL_MINUTES:
            raise ValueError("interval_minutes must be one of 15 or 60 for A1")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["session_segments"] = [list(segment) for segment in self.session_segments]
        return payload


@dataclass(frozen=True)
class ProviderSemanticFacts:
    """Facts observed from one provider surface without deriving Currentness."""

    source_token: str
    endpoint_id: str
    market: str
    symbol: str
    interval_minutes: int
    provider_timezone_name: str | None
    provider_timestamp: datetime | None
    timestamp_semantic: TimestampSemantic
    observation_complete: bool
    provenance_ref: str
    observed_at: datetime

    def __post_init__(self) -> None:
        for field_name in ("source_token", "endpoint_id", "market", "symbol", "provenance_ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{field_name} must be a non-empty trimmed string")
        if self.interval_minutes not in _SUPPORTED_INTERVAL_MINUTES:
            raise ValueError("interval_minutes must be one of 15 or 60 for A1")
        if not isinstance(self.timestamp_semantic, TimestampSemantic):
            raise ValueError("timestamp_semantic must be a TimestampSemantic")
        if not isinstance(self.observation_complete, bool):
            raise ValueError("observation_complete must be bool")
        if self.provider_timezone_name is not None:
            if not isinstance(self.provider_timezone_name, str) or not self.provider_timezone_name.strip():
                raise ValueError("provider_timezone_name must be a non-empty string or None")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")

    def to_dict(self) -> dict[str, object]:
        return {
            "source_token": self.source_token,
            "endpoint_id": self.endpoint_id,
            "market": self.market,
            "symbol": self.symbol,
            "interval_minutes": self.interval_minutes,
            "provider_timezone_name": self.provider_timezone_name,
            "provider_timestamp": self.provider_timestamp.isoformat() if self.provider_timestamp else None,
            "timestamp_semantic": self.timestamp_semantic.value,
            "observation_complete": self.observation_complete,
            "provenance_ref": self.provenance_ref,
            "observed_at": self.observed_at.isoformat(),
        }


def build_cn_intraday_identity(
    *,
    exchange: str,
    instrument_id: str,
    symbol: str,
    interval_minutes: int,
    adjustment_mode: str = "NONE",
) -> CanonicalIntradayIdentity:
    """Construct the provider-neutral A-share intraday identity for A1."""

    return CanonicalIntradayIdentity(
        market="cn",
        exchange=exchange,
        instrument_id=instrument_id,
        symbol=symbol,
        trading_calendar_id=CN_TRADING_CALENDAR_ID,
        timezone_name=CN_MARKET_TIMEZONE,
        session_segments=CN_REGULAR_SESSION_SEGMENTS,
        interval_minutes=interval_minutes,
        adjustment_mode=adjustment_mode,
    )


def _assess_provider_identity_binding(facts: ProviderSemanticFacts) -> ObservationReadiness | None:
    """Bind A1 provider facts to #40 identity plus the governed intraday surface."""

    lineage = CN_REALTIME_SOURCE_LINEAGE.get(facts.source_token)
    if lineage is None or "cn" not in lineage.markets:
        return ObservationReadiness.UNKNOWN_SOURCE_IDENTITY

    allowed_endpoints = CN_INTRADAY_ENDPOINT_EXTENSIONS.get(facts.source_token)
    if allowed_endpoints is None or facts.endpoint_id not in allowed_endpoints:
        return ObservationReadiness.INVALID_INTRADAY_ENDPOINT_BINDING

    return None


def assess_observation_readiness(
    identity: CanonicalIntradayIdentity,
    facts: ProviderSemanticFacts,
    *,
    now: datetime,
) -> ObservationReadiness:
    """Fail closed before any future Currentness/Continuity derivation.

    READY means only that the observation has enough explicit semantic evidence
    to be consumed by a later deterministic gate. It is NOT a freshness,
    Currentness, Health, actionability, SHADOW, CORE, or LIVE decision.
    """

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")

    if (
        facts.market != identity.market
        or facts.symbol != identity.symbol
        or facts.interval_minutes != identity.interval_minutes
    ):
        return ObservationReadiness.IDENTITY_MISMATCH

    provider_identity_failure = _assess_provider_identity_binding(facts)
    if provider_identity_failure is not None:
        return provider_identity_failure

    if not facts.observation_complete:
        return ObservationReadiness.PROVIDER_OBSERVATION_INCOMPLETE

    if facts.timestamp_semantic is TimestampSemantic.UNKNOWN:
        return ObservationReadiness.UNKNOWN_TIMESTAMP_SEMANTIC

    provider_timestamp = facts.provider_timestamp
    if provider_timestamp is None:
        return ObservationReadiness.MISSING_PROVIDER_TIMESTAMP
    if provider_timestamp.tzinfo is None or provider_timestamp.utcoffset() is None:
        return ObservationReadiness.NAIVE_PROVIDER_TIMESTAMP

    if facts.observed_at > now:
        return ObservationReadiness.FUTURE_OBSERVATION_TIME
    if provider_timestamp > facts.observed_at:
        return ObservationReadiness.PROVIDER_TIMESTAMP_AFTER_OBSERVED_AT
    if provider_timestamp > now:
        return ObservationReadiness.FUTURE_PROVIDER_TIMESTAMP

    return ObservationReadiness.READY_FOR_DERIVED_GATES


def observation_envelope(
    identity: CanonicalIntradayIdentity,
    facts: ProviderSemanticFacts,
    *,
    now: datetime,
) -> Mapping[str, object]:
    """Return deterministic, JSON-ready evidence without positive Currentness."""

    readiness = assess_observation_readiness(identity, facts, now=now)
    market_tz = ZoneInfo(identity.timezone_name)
    local_provider_timestamp = None
    if facts.provider_timestamp is not None and facts.provider_timestamp.tzinfo is not None:
        local_provider_timestamp = facts.provider_timestamp.astimezone(market_tz).isoformat()

    return {
        "identity": identity.to_dict(),
        "provider_facts": facts.to_dict(),
        "readiness": readiness.value,
        "provider_timestamp_market_local": local_provider_timestamp,
        "governance": {
            "same_trading_date_proves_currentness": False,
            "positive_currentness_authorized": False,
            "continuity_authorized": False,
            "live_authorized": False,
        },
    }

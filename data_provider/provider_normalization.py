"""Provider-neutral normalization for the V0.1 LiveFeed contract.

This module only translates already-observed provider payloads.  It does not
connect, subscribe, infer entitlement, or run a provider worker.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from data_provider.live_feed_types import (
    DeliveryMode,
    ProviderEvent,
    ProviderEventKind,
    SemanticStreamKey,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class CanonicalProgress:
    """Comparable source progress; receipt time is deliberately excluded."""

    provider_timestamp_utc: datetime
    sequence: int | None = None
    tie_breaker: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_timestamp_utc", _utc(self.provider_timestamp_utc))
        if self.sequence is not None and (not isinstance(self.sequence, int) or self.sequence < 0):
            raise ValueError("sequence must be a non-negative integer")
        if self.tie_breaker is not None and not self.tie_breaker:
            raise ValueError("tie_breaker must not be empty")

    def encode(self) -> str:
        return json.dumps(
            {
                "provider_timestamp": _iso(self.provider_timestamp_utc),
                "sequence": self.sequence,
                "tie_breaker": self.tie_breaker,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def decode_progress(value: str | None) -> CanonicalProgress | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        raw = json.loads(value)
        timestamp = datetime.fromisoformat(str(raw["provider_timestamp"]).replace("Z", "+00:00"))
        return CanonicalProgress(timestamp, raw.get("sequence"), raw.get("tie_breaker"))
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


def compare_progress(previous: CanonicalProgress, current: CanonicalProgress) -> int:
    """Return -1/0/1; same timestamps need a provider sequence to advance."""

    if current.provider_timestamp_utc != previous.provider_timestamp_utc:
        return (current.provider_timestamp_utc > previous.provider_timestamp_utc) - (
            current.provider_timestamp_utc < previous.provider_timestamp_utc
        )
    if previous.sequence is None or current.sequence is None:
        return 0
    if current.sequence != previous.sequence:
        return (current.sequence > previous.sequence) - (current.sequence < previous.sequence)
    # tie_breaker is opaque evidence in V0.1, not an ordering primitive.
    # A provider-specific ordering contract must be proven before it may advance continuity.
    return 0


def _delivery_mode(raw: Mapping[str, Any]) -> DeliveryMode:
    value = str(raw.get("delivery_mode", "UNKNOWN")).upper()
    try:
        return DeliveryMode(value)
    except ValueError:
        return DeliveryMode.UNKNOWN


def _progress(raw: Mapping[str, Any], provider_timestamp: datetime) -> str | None:
    if raw.get("progress_identity") is not None:
        candidate = raw["progress_identity"]
        if isinstance(candidate, str) and decode_progress(candidate) is not None:
            return candidate
        return None
    try:
        return CanonicalProgress(
            provider_timestamp,
            raw.get("sequence"),
            raw.get("tie_breaker"),
        ).encode()
    except (TypeError, ValueError):
        return None


def _data_event(
    *,
    provider_id: str,
    raw: Mapping[str, Any],
    runtime_instance_id: str,
    controller_generation: int,
    observed_at_utc: datetime,
    semantic_stream_key: SemanticStreamKey,
    provider_timestamp: datetime,
    provider_context_id: str | None = None,
    provider_connection_attempt_id: str | None = None,
) -> ProviderEvent:
    phase = str(raw.get("phase", "UNKNOWN")).upper()
    payload = dict(raw)
    payload.update(
        {
            "provider_timestamp": _iso(provider_timestamp),
            "phase": phase,
            # These are evidence fields, never inferred entitlement/finality.
            "subscription": raw.get("subscription", "UNKNOWN"),
            "usage": raw.get("usage", "UNKNOWN"),
            "entitlement": raw.get("entitlement", "UNKNOWN"),
        }
    )
    return ProviderEvent(
        runtime_instance_id=runtime_instance_id,
        provider_id=provider_id,
        controller_generation=controller_generation,
        observed_at_utc=_utc(observed_at_utc),
        observed_at_monotonic=float(raw.get("observed_at_monotonic", 0.0)),
        event_kind=ProviderEventKind.DATA,
        semantic_stream_key=semantic_stream_key,
        provider_context_id=provider_context_id,
        provider_connection_attempt_id=provider_connection_attempt_id,
        payload=payload,
        provider_timestamp_raw=_iso(provider_timestamp),
        delivery_mode=_delivery_mode(raw),
        progress_identity_candidate=_progress(raw, provider_timestamp),
        provenance=f"{provider_id}:raw_normalization_v0.1",
    )


def normalize_opend_callback(**kwargs: Any) -> ProviderEvent:
    """Normalize one already-received OpenD Kline/RTData/Ticker callback."""

    raw = kwargs.pop("raw")
    if not isinstance(raw, Mapping):
        raise TypeError("raw OpenD callback must be a mapping")
    provider_timestamp = raw.get("provider_timestamp") or raw.get("time_key") or raw.get("data_time")
    if not isinstance(provider_timestamp, datetime):
        provider_timestamp = datetime.fromisoformat(str(provider_timestamp).replace("Z", "+00:00"))
    return _data_event(provider_id="moomoo_opend", raw=raw, provider_timestamp=provider_timestamp, **kwargs)


def normalize_eastmoney_quote(**kwargs: Any) -> ProviderEvent:
    """Normalize one already-received Eastmoney quote/API row.

    Eastmoney rows default to UNKNOWN delivery and therefore cannot be
    promoted to realtime qualification without explicit independent evidence.
    """

    raw = kwargs.pop("raw")
    if not isinstance(raw, Mapping):
        raise TypeError("raw Eastmoney quote must be a mapping")
    provider_timestamp = raw.get("provider_timestamp") or raw.get("timestamp") or raw.get("date")
    if not isinstance(provider_timestamp, datetime):
        provider_timestamp = datetime.fromisoformat(str(provider_timestamp).replace("Z", "+00:00"))
    return _data_event(provider_id="eastmoney", raw=raw, provider_timestamp=provider_timestamp, **kwargs)


def normalize_opend_kline_callback(**kwargs: Any) -> ProviderEvent:
    """Normalize an already-observed OpenD K-line push conservatively."""
    raw = kwargs.pop("raw")
    if not isinstance(raw, Mapping):
        raise TypeError("raw OpenD K-line callback must be a mapping")
    normalized = dict(raw)
    normalized.setdefault("phase", "LIVE_CANDIDATE")
    normalized.setdefault("delivery_mode", "UNKNOWN")
    normalized.pop("sequence", None)
    normalized.pop("tie_breaker", None)
    return normalize_opend_callback(raw=normalized, **kwargs)


def normalize_opend_quote_callback(**kwargs: Any) -> ProviderEvent:
    """Normalize an already-observed OpenD QUOTE push fail-closed."""
    raw = kwargs.pop("raw")
    if not isinstance(raw, Mapping):
        raise TypeError("raw OpenD QUOTE callback must be a mapping")
    normalized = dict(raw)
    normalized.setdefault("phase", "LIVE_CANDIDATE")
    normalized.setdefault("delivery_mode", "UNKNOWN")
    normalized["progress_identity"] = None
    event = normalize_opend_callback(raw=normalized, **kwargs)
    return ProviderEvent(**{**event.__dict__, "progress_identity_candidate": None, "provenance": "moomoo_opend:quote_push_normalization_v0.1"})


def normalize_eastmoney_observation(**kwargs: Any) -> ProviderEvent:
    """Normalize an already-observed Eastmoney-family observation fail-closed."""
    raw = kwargs.pop("raw")
    if not isinstance(raw, Mapping):
        raise TypeError("raw Eastmoney observation must be a mapping")
    normalized = dict(raw)
    normalized.setdefault("phase", "OBSERVED")
    normalized.setdefault("delivery_mode", "UNKNOWN")
    return normalize_eastmoney_quote(raw=normalized, **kwargs)

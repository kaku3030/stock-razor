"""Synthetic-only LiveFeed qualification evidence.

This harness is intentionally not a provider worker and is not production
LIVE authority.  It consumes normalized ``ProviderEvent`` evidence so the
controller contract can be qualified without network calls, provider SDKs,
entitlement checks, or cloud runtime assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from data_provider.live_feed_types import (
    DeliveryMode,
    LifecycleState,
    ProviderEvent,
    ProviderEventKind,
    SemanticStreamKey,
)
from data_provider.market_data_adapter import MarketDataHealth
from src.services.realtime_quote_currentness import evaluate_quote_currentness


class QualificationStatus(str, Enum):
    PROVEN = "PROVEN"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class QualificationFact:
    status: QualificationStatus
    value: Any = None
    reason: str = ""


@dataclass(frozen=True)
class StreamQualification:
    semantic_stream_key: SemanticStreamKey
    lifecycle_state: LifecycleState
    provider_health: QualificationFact
    last_bar_ts: QualificationFact
    currentness: QualificationFact
    continuity: QualificationFact
    subscription_usage: QualificationFact
    evidence_scope: str = "SYNTHETIC_ONLY"
    cloud_livefeed: str = "NOT_VERIFIED"
    findings: tuple[str, ...] = ()


@dataclass
class _StreamState:
    last_progress: str | None = None
    last_bar_ts: datetime | None = None
    currentness: QualificationFact = field(
        default_factory=lambda: QualificationFact(QualificationStatus.UNKNOWN, reason="NO_CURRENTNESS_EVIDENCE")
    )
    continuity: QualificationFact = field(
        default_factory=lambda: QualificationFact(QualificationStatus.UNKNOWN, reason="NO_CONTINUITY_EVIDENCE")
    )
    live: bool = False
    findings: list[str] = field(default_factory=list)


class SyntheticLiveFeedQualificationHarness:
    """Deterministic, read-only qualification harness for normalized events.

    The harness models only data-plane qualification.  Subscription ACK is
    recorded as administrative evidence but is neither required nor enough
    for LIVE.  Provider health and subscription usage remain UNKNOWN unless
    explicitly supplied as facts by the caller; no provider entitlement is
    inferred from synthetic events.
    """

    def __init__(
        self,
        *,
        runtime_instance_id: str,
        provider_id: str,
        generation: int = 0,
        max_age_seconds: int = 60,
        provider_health: MarketDataHealth | None = None,
    ) -> None:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self._runtime_instance_id = runtime_instance_id
        self._provider_id = provider_id
        self._generation = generation
        self._max_age_seconds = max_age_seconds
        self._provider_health = provider_health
        self._connected = False
        self._states: dict[SemanticStreamKey, _StreamState] = {}

    @property
    def generation(self) -> int:
        return self._generation

    def rollover_generation(self, generation: int) -> None:
        """Start a new controller generation and revoke all prior trust."""

        if generation <= self._generation:
            raise ValueError("generation must increase")
        self._generation = generation
        self._connected = False
        self._states.clear()

    def apply(self, event: ProviderEvent) -> None:
        """Apply one normalized event; mismatched evidence is fail-closed."""

        if event.runtime_instance_id != self._runtime_instance_id or event.provider_id != self._provider_id:
            return
        if event.controller_generation != self._generation:
            return
        if event.event_kind is ProviderEventKind.CONNECTED:
            self._connected = True
            return
        if event.event_kind in (ProviderEventKind.DISCONNECTED, ProviderEventKind.ERROR):
            self._connected = False
            for state in self._states.values():
                state.live = False
                state.continuity = QualificationFact(QualificationStatus.BLOCKED, reason="TRANSPORT_NOT_CONTINUOUS")
            return
        if event.semantic_stream_key is None:
            return
        state = self._states.setdefault(event.semantic_stream_key, _StreamState())
        if event.event_kind is ProviderEventKind.SUBSCRIPTION_RESULT:
            # Administrative ACK evidence is intentionally not a qualification gate.
            state.findings.append("SUBSCRIPTION_ACK_ADMINISTRATIVE_ONLY")
            return
        if event.event_kind is not ProviderEventKind.DATA:
            return

        payload: Mapping[str, Any] = event.payload or {}
        if str(payload.get("phase", "")).upper() in {"SEED", "RECOVERY_BACKFILL"}:
            state.findings.append("NON_LIVE_DATA_PHASE")
            return
        if event.delivery_mode is not DeliveryMode.REALTIME:
            state.live = False
            state.currentness = QualificationFact(QualificationStatus.BLOCKED, reason="DELIVERY_MODE_NOT_REALTIME")
            state.continuity = QualificationFact(QualificationStatus.BLOCKED, reason="DELIVERY_MODE_NOT_REALTIME")
            return

        provider_timestamp = payload.get("provider_timestamp", event.provider_timestamp_raw)
        progress = event.progress_identity_candidate or payload.get("progress_identity")
        quote = {
            "provider_timestamp": provider_timestamp,
            "data_quality": payload.get("data_quality", "ok"),
            "source": self._provider_id,
            "is_stale": payload.get("is_stale"),
            "stale_seconds": payload.get("stale_seconds"),
        }
        now = event.observed_at_utc.astimezone(timezone.utc)
        decision = evaluate_quote_currentness(quote, max_age_seconds=self._max_age_seconds, now_utc=now)
        if not decision.currentness_passed:
            state.live = False
            state.currentness = QualificationFact(QualificationStatus.BLOCKED, reason=decision.reason)
            state.continuity = QualificationFact(QualificationStatus.BLOCKED, reason="CURRENTNESS_NOT_PROVEN")
            return
        if not isinstance(progress, str) or not progress:
            state.live = False
            state.currentness = QualificationFact(QualificationStatus.BLOCKED, reason="MISSING_PROGRESS_IDENTITY")
            state.continuity = QualificationFact(QualificationStatus.BLOCKED, reason="MISSING_PROGRESS_IDENTITY")
            return

        state.last_bar_ts = decision.provider_timestamp
        state.currentness = QualificationFact(
            QualificationStatus.PROVEN, value=decision.provider_timestamp, reason="CURRENTNESS_PROVEN"
        )
        if state.last_progress is None:
            state.last_progress = progress
            state.continuity = QualificationFact(QualificationStatus.UNKNOWN, reason="WAITING_FOR_LATER_PROGRESS")
            state.live = False
            return
        if progress <= state.last_progress:
            state.findings.append("NO_PROGRESS_DUPLICATE_OR_OLD")
            state.continuity = QualificationFact(QualificationStatus.BLOCKED, reason="NO_STRICTLY_LATER_PROGRESS")
            state.live = False
            return
        state.last_progress = progress
        state.continuity = QualificationFact(QualificationStatus.PROVEN, reason="CONTINUITY_PROVEN")
        state.live = self._connected

    def snapshot(self, key: SemanticStreamKey) -> StreamQualification:
        state = self._states.get(key, _StreamState())
        if state.live:
            lifecycle = LifecycleState.LIVE
        elif self._connected:
            lifecycle = LifecycleState.CONNECTED
        else:
            lifecycle = LifecycleState.DISCONNECTED
        health = (
            QualificationFact(QualificationStatus.PROVEN, self._provider_health, reason="SUPPLIED_HEALTH_FACT")
            if self._provider_health is not None
            else QualificationFact(QualificationStatus.UNKNOWN, reason="PROVIDER_HEALTH_NOT_SUPPLIED")
        )
        last_bar = (
            QualificationFact(QualificationStatus.PROVEN, state.last_bar_ts, reason="PROVIDER_BAR_TIMESTAMP")
            if state.last_bar_ts is not None
            else QualificationFact(QualificationStatus.UNKNOWN, reason="LAST_BAR_TIMESTAMP_UNKNOWN")
        )
        return StreamQualification(
            semantic_stream_key=key,
            lifecycle_state=lifecycle,
            provider_health=health,
            last_bar_ts=last_bar,
            currentness=state.currentness,
            continuity=state.continuity,
            subscription_usage=QualificationFact(
                QualificationStatus.UNKNOWN, reason="SYNTHETIC_EVIDENCE_HAS_NO_ENTITLEMENT_USAGE"
            ),
            findings=tuple(state.findings),
        )

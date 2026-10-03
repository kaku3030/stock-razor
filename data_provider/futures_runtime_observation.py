"""Read-only runtime observation for the futures qualification boundary.

This module wraps the existing history/source abstraction.  It records what
was observed, but it never upgrades Yahoo delivery, emits signals, or places
orders.  A runtime sample is evidence with an explicit provider scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from data_provider.futures_qualification import (
    FuturesSessionPolicy,
    evaluate_futures_currentness,
)
from data_provider.live_feed_types import (
    DeliveryMode,
    ProviderEvent,
    ProviderEventKind,
    SemanticStreamKey,
)
from data_provider.provider_normalization import compare_progress, decode_progress
from src.services.live_feed.qualification import (
    FuturesLiveFeedQualificationHarness,
    QualificationStatus,
)


_TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


@dataclass(frozen=True)
class FuturesRuntimeObservation:
    evidence_scope: str
    provider_id: str
    runtime_instance_id: str
    generation: int
    root: str
    stream_key: SemanticStreamKey | None
    event_kind: str
    observed_at_utc: datetime
    provider_timestamp: datetime | None
    age_seconds: float | None
    progress_identity: str | None
    currentness_status: str
    currentness_reason: str
    continuity_status: str
    continuity_reason: str
    gap_status: str
    session_phase: str | None
    transport_transition: str
    contract_identity: str | None
    feed_semantics: str | None
    delivery_mode: str
    entitlement: str
    qualification_status: str
    error: str | None = None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


class FuturesRuntimeObserver:
    """Observe repeated samples through the existing futures abstraction."""

    def __init__(
        self,
        *,
        runtime_instance_id: str,
        session_policy: FuturesSessionPolicy,
        max_age_seconds: int = 900,
        provider_id: str = "yahoo_finance",
    ) -> None:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self._runtime_instance_id = runtime_instance_id
        self._provider_id = provider_id
        self._session_policy = session_policy
        self._max_age_seconds = max_age_seconds
        self._generation = 0
        self._transport = "DISCONNECTED"
        self._last_progress: dict[SemanticStreamKey, Any] = {}
        self._last_provider_timestamp: dict[SemanticStreamKey, datetime] = {}
        self._harness = FuturesLiveFeedQualificationHarness(
            runtime_instance_id=runtime_instance_id,
            provider_id=provider_id,
            session_policy=session_policy,
            max_age_seconds=max_age_seconds,
        )
        self._observations: list[FuturesRuntimeObservation] = []

    @property
    def observations(self) -> tuple[FuturesRuntimeObservation, ...]:
        return tuple(self._observations)

    def rollover_generation(self, generation: int, *, observed_at_utc: datetime) -> FuturesRuntimeObservation:
        if generation <= self._generation:
            raise ValueError("generation must increase")
        self._generation = generation
        self._transport = "DISCONNECTED"
        self._last_progress.clear()
        self._last_provider_timestamp.clear()
        self._harness.rollover_generation(generation)
        return self._record_transition(observed_at_utc, "GENERATION_ROLLOVER")

    def record_transport(
        self,
        event_kind: ProviderEventKind,
        *,
        observed_at_utc: datetime,
        error: str | None = None,
    ) -> FuturesRuntimeObservation:
        if event_kind is ProviderEventKind.CONNECTED:
            transition = "RECOVERED" if self._transport in {"ERROR", "DISCONNECTED"} else "CONNECTED"
            self._transport = "CONNECTED"
        elif event_kind is ProviderEventKind.DISCONNECTED:
            transition = "DISCONNECTED"
            self._transport = "DISCONNECTED"
        elif event_kind is ProviderEventKind.ERROR:
            transition = "ERROR"
            self._transport = "ERROR"
        else:
            raise ValueError("unsupported transport event")
        self._harness.apply(
            ProviderEvent(
                runtime_instance_id=self._runtime_instance_id,
                provider_id=self._provider_id,
                controller_generation=self._generation,
                observed_at_utc=_utc(observed_at_utc),
                observed_at_monotonic=0.0,
                event_kind=event_kind,
            )
        )
        return self._record_transition(observed_at_utc, transition, error=error, event_kind=event_kind.value)

    def sample(
        self,
        fetch: Callable[..., list[ProviderEvent]],
        root: str,
        timeframe: str,
        *,
        observed_at_utc: datetime,
        **kwargs: Any,
    ) -> tuple[FuturesRuntimeObservation, ...]:
        """Fetch one read-only sample; callers may invoke this repeatedly."""

        now = _utc(observed_at_utc)
        try:
            events = fetch(root, timeframe, observed_at_utc=now, **kwargs)
        except Exception as exc:  # source failure is runtime evidence, not a crash claim
            return (self.record_transport(ProviderEventKind.ERROR, observed_at_utc=now, error=type(exc).__name__),)
        if self._transport in {"ERROR", "DISCONNECTED"}:
            self.record_transport(ProviderEventKind.CONNECTED, observed_at_utc=now)
        result = tuple(self.observe_event(event) for event in events)
        return result

    def observe_event(self, event: ProviderEvent) -> FuturesRuntimeObservation:
        self._harness.apply(event)
        key = event.semantic_stream_key
        payload = event.payload or {}
        decision = evaluate_futures_currentness(
            event,
            now_utc=event.observed_at_utc,
            session_policy=self._session_policy,
            max_age_seconds=self._max_age_seconds,
        )
        provider_timestamp = decision.provider_timestamp
        progress = event.progress_identity_candidate or payload.get("progress_identity")
        previous = self._last_progress.get(key) if key is not None else None
        parsed = decode_progress(progress) if isinstance(progress, str) else None
        if key is None or parsed is None or previous is None:
            continuity_status, continuity_reason, gap_status = "UNKNOWN", "WAITING_FOR_LATER_PROGRESS", "NOT_EVALUATED"
        else:
            ordering = compare_progress(previous, parsed)
            continuity_status = "PROVEN" if ordering > 0 else "BLOCKED"
            continuity_reason = "CONTINUITY_PROVEN" if ordering > 0 else "NO_STRICTLY_LATER_PROGRESS"
            prior_ts = self._last_provider_timestamp.get(key)
            interval = _TIMEFRAME_SECONDS.get(key.timeframe or "")
            gap_status = (
                "GAP"
                if prior_ts and provider_timestamp and interval and (provider_timestamp - prior_ts).total_seconds() > interval
                else "NO_GAP"
            )
        if key is not None and parsed is not None:
            self._last_progress[key] = parsed
        if key is not None and provider_timestamp is not None:
            self._last_provider_timestamp[key] = provider_timestamp
        snap = self._harness.snapshot(key) if key is not None else None
        qualified = "CANDIDATE_NOT_REALTIME" if decision.passed and snap and snap.continuity.status is QualificationStatus.PROVEN else "BLOCKED"
        contract = payload.get("contract_symbol") or payload.get("vendor_symbol")
        observation = FuturesRuntimeObservation(
            evidence_scope="RUNTIME_OBSERVATION",
            provider_id=event.provider_id,
            runtime_instance_id=event.runtime_instance_id,
            generation=event.controller_generation,
            root=key.symbol if key else "UNKNOWN",
            stream_key=key,
            event_kind=event.event_kind.value,
            observed_at_utc=_utc(event.observed_at_utc),
            provider_timestamp=provider_timestamp,
            age_seconds=decision.age_seconds,
            progress_identity=progress if isinstance(progress, str) else None,
            currentness_status="PROVEN" if decision.passed else "BLOCKED",
            currentness_reason=decision.reason,
            continuity_status=continuity_status,
            continuity_reason=continuity_reason,
            gap_status=gap_status,
            session_phase=decision.session_phase.value if decision.session_phase else None,
            transport_transition="SAMPLE",
            contract_identity=contract,
            feed_semantics=payload.get("continuous_semantics"),
            delivery_mode=DeliveryMode.UNKNOWN.value,
            entitlement="UNKNOWN",
            qualification_status=qualified,
        )
        self._observations.append(observation)
        return observation

    def _record_transition(
        self,
        observed_at_utc: datetime,
        transition: str,
        *,
        error: str | None = None,
        event_kind: str = "TRANSITION",
    ) -> FuturesRuntimeObservation:
        observation = FuturesRuntimeObservation(
            evidence_scope="RUNTIME_OBSERVATION",
            provider_id=self._provider_id,
            runtime_instance_id=self._runtime_instance_id,
            generation=self._generation,
            root="UNKNOWN",
            stream_key=None,
            event_kind=event_kind,
            observed_at_utc=_utc(observed_at_utc),
            provider_timestamp=None,
            age_seconds=None,
            progress_identity=None,
            currentness_status="UNKNOWN",
            currentness_reason="NO_DATA_EVENT",
            continuity_status="BLOCKED" if transition in {"ERROR", "DISCONNECTED", "GENERATION_ROLLOVER"} else "UNKNOWN",
            continuity_reason="TRANSPORT_NOT_CONTINUOUS" if transition in {"ERROR", "DISCONNECTED"} else "GENERATION_NOT_ESTABLISHED",
            gap_status="NOT_EVALUATED",
            session_phase=None,
            transport_transition=transition,
            contract_identity=None,
            feed_semantics=None,
            delivery_mode=DeliveryMode.UNKNOWN.value,
            entitlement="UNKNOWN",
            qualification_status="BLOCKED",
            error=error,
        )
        self._observations.append(observation)
        return observation

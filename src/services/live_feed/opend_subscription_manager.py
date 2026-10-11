"""Instance-scoped, fail-closed OpenD subscription orchestration.

The existing Futu/OpenD owner supplies the adapter.  This module owns only
candidate intent and the provider state that this instance has observed; it
does not create a context, query a provider, restart a service, or qualify a
feed as realtime/live.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence

from data_provider.live_feed_types import SemanticStreamKey


class SubscriptionMutationAdapter(Protocol):
    """The narrow mutation surface supplied by the existing OpenD owner."""

    def subscribe_streams(self, keys: Sequence[SemanticStreamKey]) -> None:
        ...

    def unsubscribe_stream(self, key: SemanticStreamKey) -> None:
        ...


@dataclass(frozen=True)
class OpenDSubscriptionQuota:
    """A separately observed, bounded aggregate quota fact."""

    total_used: int | None
    remaining: int | None
    observed_at_utc: datetime | None
    verified: bool = False


@dataclass(frozen=True)
class HistoryWarmStartEvidence:
    """Explicit evidence for a research-cache warm start.

    This is intentionally not a realtime or LIVE qualification contract.
    ``evidence_id`` is required so an absent result cannot look like a pass.
    """

    status: str
    evidence_id: str | None
    research_cache_seed_eligible: bool = False
    realtime_currentness_proven: bool = False


@dataclass(frozen=True)
class HistoryWarmStartState:
    key: SemanticStreamKey
    status: str
    evidence_id: str | None
    reason: str | None
    realtime_qualification: str = "UNKNOWN"


@dataclass(frozen=True)
class HistoryWarmStartResult:
    status: str
    key: SemanticStreamKey
    reason: str | None
    realtime_qualification: str = "UNKNOWN"


@dataclass(frozen=True)
class SubscriptionMutationResult:
    status: str
    reason: str | None
    added: tuple[SemanticStreamKey, ...]
    removed: tuple[SemanticStreamKey, ...]
    transport_mutations_attempted: int
    candidate_pool: tuple[SemanticStreamKey, ...]
    applied: tuple[SemanticStreamKey, ...]


@dataclass(frozen=True)
class OpenDSubscriptionManagerSnapshot:
    runtime_instance_id: str
    candidate_pool: tuple[SemanticStreamKey, ...]
    applied: tuple[SemanticStreamKey, ...]
    transport_state: str
    last_recovery_token: str | None
    history_warm_start: tuple[HistoryWarmStartState, ...]
    realtime_qualification: str = "UNKNOWN"
    radar_admission: str = "BLOCKED"
    source_arbiter_admission: str = "BLOCKED"
    live_trade: bool = False


def _default_now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _key_sort(key: SemanticStreamKey) -> tuple[str, ...]:
    return (
        key.provider_id,
        key.market,
        key.symbol,
        key.stream_type,
        key.timeframe or "",
        key.session_mode or "",
        key.adjustment_mode or "",
        key.feed or "",
    )


def _validate_key(key: object) -> str | None:
    if not isinstance(key, SemanticStreamKey):
        return "INVALID_STREAM_KEY"
    if (
        key.provider_id != "futu"
        or key.market != "us"
        or key.stream_type != "K_1M"
        or key.timeframe != "1m"
        or not key.symbol.startswith("US.")
        or key.symbol != key.symbol.upper()
    ):
        return "UNSUPPORTED_OPEND_STREAM_KEY"
    return None


class OpenDSubscriptionManager:
    """Reconcile one instance's desired K_1M pool against an injected owner.

    Provider calls are made only for deltas.  An exception leaves the provider
    state UNKNOWN because a batch or individual mutation may have partially
    applied; a new recovery token is then required before another mutation.
    """

    def __init__(
        self,
        adapter: SubscriptionMutationAdapter,
        *,
        runtime_instance_id: str,
        now_utc: Callable[[], datetime] = _default_now_utc,
        quota_max_age_seconds: int = 120,
    ) -> None:
        instance_id = str(runtime_instance_id or "").strip()
        if not instance_id:
            raise ValueError("runtime_instance_id must not be empty")
        if type(quota_max_age_seconds) is not int or quota_max_age_seconds <= 0:
            raise ValueError("quota_max_age_seconds must be a positive integer")
        self._adapter = adapter
        self._runtime_instance_id = instance_id
        self._now_utc = now_utc
        self._quota_max_age_seconds = quota_max_age_seconds
        self._lock = threading.RLock()
        self._candidate_pool: set[SemanticStreamKey] = set()
        self._applied: set[SemanticStreamKey] = set()
        self._transport_state = "KNOWN"
        self._last_recovery_token: str | None = None
        self._history: dict[SemanticStreamKey, HistoryWarmStartState] = {}

    def snapshot(self) -> OpenDSubscriptionManagerSnapshot:
        with self._lock:
            return OpenDSubscriptionManagerSnapshot(
                runtime_instance_id=self._runtime_instance_id,
                candidate_pool=self._ordered(self._candidate_pool),
                applied=self._ordered(self._applied),
                transport_state=self._transport_state,
                last_recovery_token=self._last_recovery_token,
                history_warm_start=tuple(
                    self._history[key] for key in sorted(self._history, key=_key_sort)
                ),
            )

    def add(
        self,
        key: SemanticStreamKey,
        *,
        quota: OpenDSubscriptionQuota | None = None,
    ) -> SubscriptionMutationResult:
        with self._lock:
            reason = _validate_key(key)
            if reason:
                return self._blocked(reason)
            return self.update_candidates(
                (*self._candidate_pool, key),
                quota=quota,
            )

    def remove(
        self,
        key: SemanticStreamKey,
        *,
        quota: OpenDSubscriptionQuota | None = None,
    ) -> SubscriptionMutationResult:
        with self._lock:
            reason = _validate_key(key)
            if reason:
                return self._blocked(reason)
            return self.update_candidates(
                tuple(candidate for candidate in self._candidate_pool if candidate != key),
                quota=quota,
            )

    def update_candidates(
        self,
        candidates: Sequence[SemanticStreamKey],
        *,
        quota: OpenDSubscriptionQuota | None = None,
    ) -> SubscriptionMutationResult:
        """Replace this instance's candidate pool and reconcile its deltas."""

        with self._lock:
            try:
                materialized = tuple(candidates)
            except TypeError:
                return self._blocked("INVALID_CANDIDATE_POOL")
            for key in materialized:
                reason = _validate_key(key)
                if reason:
                    return self._blocked(reason)
            self._candidate_pool = set(materialized)
            return self._reconcile(quota=quota)

    def recover(
        self,
        recovery_token: str,
        *,
        quota: OpenDSubscriptionQuota | None = None,
    ) -> SubscriptionMutationResult:
        """Rebind to one externally established transport incarnation.

        The token is supplied by the existing owner after it observes a new
        recovery incarnation.  Reusing a token is always a no-op.  This method
        does not restart OpenD and never clears provider subscriptions globally.
        """

        with self._lock:
            token = str(recovery_token or "").strip()
            if not token:
                return self._blocked("RECOVERY_TOKEN_REQUIRED")
            if token == self._last_recovery_token:
                return self._result("NOOP", "RECOVERY_ALREADY_APPLIED")

            desired = self._ordered(self._candidate_pool)
            if desired:
                quota_reason = self._quota_reason(quota, required_additions=len(desired))
                if quota_reason:
                    return self._blocked(quota_reason)

            self._applied.clear()
            self._transport_state = "KNOWN"
            self._last_recovery_token = token
            if not desired:
                return self._result("NOOP", "RECOVERY_EMPTY_CANDIDATE_POOL")
            try:
                self._adapter.subscribe_streams(desired)
            except Exception:
                self._transport_state = "UNKNOWN"
                return self._result(
                    "UNKNOWN",
                    "TRANSPORT_MUTATION_OUTCOME_UNKNOWN",
                    attempted=1,
                )
            self._applied = set(desired)
            return self._result("RECOVERED", None, added=desired, attempted=1)

    def record_history_warm_start(
        self,
        key: SemanticStreamKey,
        evidence: HistoryWarmStartEvidence | None,
    ) -> HistoryWarmStartResult:
        """Record research-cache evidence without promoting realtime status."""

        with self._lock:
            reason = _validate_key(key)
            if reason:
                return HistoryWarmStartResult("UNKNOWN", key, reason)
            if evidence is None:
                state = HistoryWarmStartState(
                    key, "UNKNOWN", None, "HISTORY_WARM_START_EVIDENCE_MISSING"
                )
            elif evidence.realtime_currentness_proven:
                state = HistoryWarmStartState(
                    key,
                    "UNKNOWN",
                    evidence.evidence_id,
                    "HISTORICAL_EVIDENCE_CANNOT_PROVE_REALTIME",
                )
            elif (
                evidence.status == "PASS"
                and evidence.research_cache_seed_eligible is True
                and isinstance(evidence.evidence_id, str)
                and bool(evidence.evidence_id.strip())
            ):
                state = HistoryWarmStartState(key, "PASS", evidence.evidence_id, None)
            else:
                state = HistoryWarmStartState(
                    key,
                    "UNKNOWN",
                    evidence.evidence_id,
                    "HISTORY_WARM_START_NOT_PROVEN",
                )
            self._history[key] = state
            return HistoryWarmStartResult(
                state.status,
                key,
                state.reason,
                state.realtime_qualification,
            )

    def warm_start(
        self,
        key: SemanticStreamKey,
        evidence: HistoryWarmStartEvidence | None,
    ) -> HistoryWarmStartResult:
        """Short alias for callers that model warm-start as an operation."""

        return self.record_history_warm_start(key, evidence)

    def _reconcile(self, *, quota: OpenDSubscriptionQuota | None) -> SubscriptionMutationResult:
        if self._transport_state == "UNKNOWN":
            return self._blocked("TRANSPORT_STATE_UNKNOWN")
        additions = self._ordered(self._candidate_pool - self._applied)
        removals = self._ordered(self._applied - self._candidate_pool)
        if additions:
            quota_reason = self._quota_reason(quota, required_additions=len(additions))
            if quota_reason:
                return self._blocked(quota_reason)
        if not additions and not removals:
            return self._result("NOOP", "ALREADY_RECONCILED")

        attempted = 0
        try:
            if additions:
                attempted += 1
                self._adapter.subscribe_streams(additions)
            for key in removals:
                attempted += 1
                self._adapter.unsubscribe_stream(key)
        except Exception:
            self._transport_state = "UNKNOWN"
            return self._result(
                "UNKNOWN",
                "TRANSPORT_MUTATION_OUTCOME_UNKNOWN",
                attempted=attempted,
            )
        self._applied = set(self._candidate_pool)
        return self._result("APPLIED", None, added=additions, removed=removals, attempted=attempted)

    def _quota_reason(
        self,
        quota: OpenDSubscriptionQuota | None,
        *,
        required_additions: int,
    ) -> str | None:
        if quota is None:
            return "QUOTA_OBSERVATION_REQUIRED"
        if quota.verified is not True:
            return "QUOTA_UNVERIFIED"
        if type(quota.total_used) is not int or type(quota.remaining) is not int:
            return "QUOTA_FIELDS_UNKNOWN"
        if quota.total_used < 0 or quota.remaining < 0 or quota.total_used + quota.remaining > 10000:
            return "QUOTA_FIELDS_INVALID"
        observed = quota.observed_at_utc
        if not isinstance(observed, datetime) or observed.tzinfo is None or observed.utcoffset() is None:
            return "QUOTA_OBSERVATION_TIMESTAMP_REQUIRED"
        now = self._now_utc()
        if now.tzinfo is None or now.utcoffset() is None:
            return "INVALID_CLOCK"
        age = (now.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
        if not -5 <= age <= self._quota_max_age_seconds:
            return "STALE_OR_FUTURE_QUOTA_OBSERVATION"
        if required_additions > quota.remaining:
            return "QUOTA_EXCEEDED"
        return None

    def _blocked(self, reason: str) -> SubscriptionMutationResult:
        return self._result("BLOCKED", reason)

    def _result(
        self,
        status: str,
        reason: str | None,
        *,
        added: tuple[SemanticStreamKey, ...] = (),
        removed: tuple[SemanticStreamKey, ...] = (),
        attempted: int = 0,
    ) -> SubscriptionMutationResult:
        return SubscriptionMutationResult(
            status=status,
            reason=reason,
            added=added,
            removed=removed,
            transport_mutations_attempted=attempted,
            candidate_pool=self._ordered(self._candidate_pool),
            applied=self._ordered(self._applied),
        )

    @staticmethod
    def _ordered(keys: set[SemanticStreamKey] | Sequence[SemanticStreamKey]) -> tuple[SemanticStreamKey, ...]:
        return tuple(sorted(keys, key=_key_sort))


SubscriptionQuota = OpenDSubscriptionQuota

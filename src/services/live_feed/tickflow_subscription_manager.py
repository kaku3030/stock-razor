"""Fail-closed dynamic TickFlow subscription control plane.

This module owns desired symbols and transport acknowledgements only. It does
not create a TickFlow client, read credentials, infer entitlement, or qualify
realtime continuity.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol, Sequence

from data_provider.live_feed_types import SemanticStreamKey


class TickFlowSubscriptionTransport(Protocol):
    def subscribe(self, keys: Sequence[SemanticStreamKey]) -> bool: ...
    def unsubscribe(self, keys: Sequence[SemanticStreamKey]) -> bool: ...


@dataclass(frozen=True)
class TickFlowSubscriptionResult:
    status: str
    reason: str | None
    added: tuple[SemanticStreamKey, ...] = ()
    removed: tuple[SemanticStreamKey, ...] = ()
    candidate_pool: tuple[SemanticStreamKey, ...] = ()
    applied: tuple[SemanticStreamKey, ...] = ()
    transport_mutations_attempted: int = 0


@dataclass(frozen=True)
class TickFlowSubscriptionSnapshot:
    candidate_pool: tuple[SemanticStreamKey, ...]
    applied: tuple[SemanticStreamKey, ...]
    transport_state: str
    last_recovery_token: str | None
    last_mutation_at_utc: datetime | None
    realtime_qualification: str = "UNKNOWN"
    radar_admission: str = "BLOCKED"
    source_arbiter_admission: str = "BLOCKED"
    live_trade: bool = False


_CN_EQUITY = re.compile(r"(?:SH|SZ|BJ)\.[0-9]{6}\Z")


def _key_sort(key: SemanticStreamKey) -> tuple[str, ...]:
    return (key.provider_id, key.market, key.symbol, key.stream_type, key.timeframe or "")


def _validate_key(key: object) -> str | None:
    if not isinstance(key, SemanticStreamKey):
        return "INVALID_STREAM_KEY"
    if (
        key.provider_id != "tickflow"
        or key.market != "cn"
        or key.stream_type != "QUOTE"
        or key.timeframe not in (None, "tick")
        or not isinstance(key.symbol, str)
        or _CN_EQUITY.fullmatch(key.symbol.upper()) is None
    ):
        return "UNSUPPORTED_TICKFLOW_STREAM_KEY"
    return None


class TickFlowSubscriptionManager:
    """Reconcile a bounded CN candidate pool through explicit transport ACKs."""

    def __init__(
        self,
        transport: TickFlowSubscriptionTransport,
        *,
        now_utc: Callable[[], datetime],
        max_symbols: int = 50,
        min_mutation_interval_seconds: int = 0,
    ) -> None:
        if type(max_symbols) is not int or max_symbols < 1:
            raise ValueError("max_symbols must be a positive integer")
        if type(min_mutation_interval_seconds) is not int or min_mutation_interval_seconds < 0:
            raise ValueError("min_mutation_interval_seconds must be non-negative")
        self._transport = transport
        self._now_utc = now_utc
        self._max_symbols = max_symbols
        self._min_mutation_interval_seconds = min_mutation_interval_seconds
        self._lock = threading.RLock()
        self._candidate_pool: set[SemanticStreamKey] = set()
        self._applied: set[SemanticStreamKey] = set()
        self._transport_state = "KNOWN"
        self._last_recovery_token: str | None = None
        self._last_mutation_at_utc: datetime | None = None

    def snapshot(self) -> TickFlowSubscriptionSnapshot:
        with self._lock:
            return TickFlowSubscriptionSnapshot(
                self._ordered(self._candidate_pool), self._ordered(self._applied),
                self._transport_state, self._last_recovery_token,
                self._last_mutation_at_utc,
            )

    def update_candidates(self, candidates: Sequence[SemanticStreamKey]) -> TickFlowSubscriptionResult:
        with self._lock:
            try:
                incoming = tuple(candidates)
            except TypeError:
                return self._blocked("INVALID_CANDIDATE_POOL")
            if len(incoming) > self._max_symbols:
                return self._blocked("CANDIDATE_LIMIT")
            if len(set(incoming)) != len(incoming):
                return self._blocked("DUPLICATE_STREAM_KEY")
            for key in incoming:
                reason = _validate_key(key)
                if reason:
                    return self._blocked(reason)
            self._candidate_pool = set(incoming)
            return self._reconcile()

    def recover(self, recovery_token: str) -> TickFlowSubscriptionResult:
        with self._lock:
            token = str(recovery_token or "").strip()
            if not token:
                return self._blocked("RECOVERY_TOKEN_REQUIRED")
            if token == self._last_recovery_token:
                return self._result("NOOP", "RECOVERY_ALREADY_APPLIED")
            if self._rate_limited():
                return self._blocked("MUTATION_RATE_LIMITED")
            desired = self._ordered(self._candidate_pool)
            self._last_recovery_token = token
            self._applied.clear()
            self._transport_state = "KNOWN"
            if not desired:
                return self._result("NOOP", "RECOVERY_EMPTY_CANDIDATE_POOL")
            self._last_mutation_at_utc = self._utc_now()
            if not self._call_subscribe(desired):
                self._transport_state = "UNKNOWN"
                return self._result("UNKNOWN", "SUBSCRIPTION_ACK_NOT_VERIFIED", attempted=1)
            self._applied = set(desired)
            return self._result("RECOVERED", None, added=desired, attempted=1)

    def _reconcile(self) -> TickFlowSubscriptionResult:
        if self._transport_state == "UNKNOWN":
            return self._blocked("TRANSPORT_STATE_UNKNOWN")
        additions = self._ordered(self._candidate_pool - self._applied)
        removals = self._ordered(self._applied - self._candidate_pool)
        if not additions and not removals:
            return self._result("NOOP", "ALREADY_RECONCILED")
        if self._rate_limited():
            return self._blocked("MUTATION_RATE_LIMITED")
        attempted = 0
        self._last_mutation_at_utc = self._utc_now()
        if additions:
            attempted += 1
            if not self._call_subscribe(additions):
                self._transport_state = "UNKNOWN"
                return self._result("UNKNOWN", "SUBSCRIPTION_ACK_NOT_VERIFIED", attempted=attempted)
        for key in removals:
            attempted += 1
            if not self._call_unsubscribe((key,)):
                self._transport_state = "UNKNOWN"
                return self._result("UNKNOWN", "UNSUBSCRIPTION_ACK_NOT_VERIFIED", attempted=attempted)
        self._applied = set(self._candidate_pool)
        return self._result("APPLIED", None, added=additions, removed=removals, attempted=attempted)

    def _call_subscribe(self, keys: Sequence[SemanticStreamKey]) -> bool:
        try:
            return self._transport.subscribe(keys) is True
        except Exception:
            return False

    def _call_unsubscribe(self, keys: Sequence[SemanticStreamKey]) -> bool:
        try:
            return self._transport.unsubscribe(keys) is True
        except Exception:
            return False

    def _rate_limited(self) -> bool:
        if self._min_mutation_interval_seconds == 0 or self._last_mutation_at_utc is None:
            return False
        return (self._utc_now() - self._last_mutation_at_utc).total_seconds() < self._min_mutation_interval_seconds

    def _utc_now(self) -> datetime:
        now = self._now_utc()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_utc must return an aware datetime")
        return now.astimezone(timezone.utc)

    def _blocked(self, reason: str) -> TickFlowSubscriptionResult:
        return self._result("BLOCKED", reason)

    def _result(self, status: str, reason: str | None, *, added=(), removed=(), attempted=0):
        return TickFlowSubscriptionResult(
            status, reason, added, removed, self._ordered(self._candidate_pool),
            self._ordered(self._applied), attempted,
        )

    @staticmethod
    def _ordered(keys: set[SemanticStreamKey] | Sequence[SemanticStreamKey]) -> tuple[SemanticStreamKey, ...]:
        return tuple(sorted(keys, key=_key_sort))

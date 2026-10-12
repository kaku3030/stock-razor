"""Provider Read Boundary R1: provider-neutral, fake/stub-only evidence seam.

This module deliberately has no provider SDK imports and no production wiring.
It describes transport facts only; downstream owners decide freshness, health,
portfolio trust, and actionability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Mapping

from data_provider.live_feed_types import freeze_normalized_payload
from .provider_worker_contracts import ProviderExecutionOutcome


class ReadOperation(str, Enum):
    QUOTE_SNAPSHOT = "QUOTE_SNAPSHOT"
    HISTORY_KLINE = "HISTORY_KLINE"
    TRADING_DAYS = "TRADING_DAYS"
    ACCOUNT_LIST = "ACCOUNT_LIST"
    POSITION_LIST = "POSITION_LIST"


@dataclass(frozen=True)
class QuoteSnapshotParams:
    symbols: tuple[str, ...]

@dataclass(frozen=True)
class HistoryKlineParams:
    symbol: str
    timeframe: str
    start: date
    end: date
    max_count: int

@dataclass(frozen=True)
class TradingDaysParams:
    market: str
    start: date
    end: date

@dataclass(frozen=True)
class AccountListParams:
    scope: str = "READ_ONLY"

@dataclass(frozen=True)
class PositionListParams:
    account_id: str
    scope: str = "READ_ONLY"


_PARAMS = {ReadOperation.QUOTE_SNAPSHOT: QuoteSnapshotParams,
           ReadOperation.HISTORY_KLINE: HistoryKlineParams,
           ReadOperation.TRADING_DAYS: TradingDaysParams,
           ReadOperation.ACCOUNT_LIST: AccountListParams,
           ReadOperation.POSITION_LIST: PositionListParams}


@dataclass(frozen=True)
class ProviderReadRequest:
    runtime_instance_id: str
    provider_id: str
    request_id: str
    operation: ReadOperation
    created_at_utc: datetime
    params: Any

    def __post_init__(self) -> None:
        for name, value in (("runtime_instance_id", self.runtime_instance_id), ("provider_id", self.provider_id), ("request_id", self.request_id)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-blank string")
        if type(self.operation) is not ReadOperation or not isinstance(self.params, _PARAMS[self.operation]):
            raise TypeError("operation requires its typed parameter object")
        if self.created_at_utc.tzinfo is None or self.created_at_utc.utcoffset() is None:
            raise ValueError("created_at_utc must be UTC-aware")
        if self.created_at_utc.astimezone(timezone.utc) != self.created_at_utc:
            raise ValueError("created_at_utc must use UTC")
        if self.operation is ReadOperation.QUOTE_SNAPSHOT and (not self.params.symbols or any(not s for s in self.params.symbols)):
            raise ValueError("symbols must be a non-empty tuple")
        if hasattr(self.params, "max_count") and not 0 < self.params.max_count <= 10000:
            raise ValueError("max_count out of bounds")


@dataclass(frozen=True)
class ProviderReadOutcome:
    runtime_instance_id: str
    provider_id: str
    worker_generation: int | None
    request: ProviderReadRequest
    execution_outcome: ProviderExecutionOutcome
    dispatched_at_monotonic_ns: int | None
    terminal_observed_at_monotonic_ns: int
    terminal_at_utc: datetime
    provider_error_code: str | None = None
    provider_error_message: str | None = None
    normalized_provider_payload: Any = None
    diagnostic_reason: str | None = None

    def __post_init__(self) -> None:
        if (self.runtime_instance_id, self.provider_id) != (self.request.runtime_instance_id, self.request.provider_id):
            raise ValueError("outcome envelope must match request identity")
        if type(self.execution_outcome) is not ProviderExecutionOutcome:
            raise TypeError("execution_outcome must use the authoritative enum")
        if self.worker_generation is None:
            if self.execution_outcome is not ProviderExecutionOutcome.CANCELLED_GENERATION_INVALIDATED or self.dispatched_at_monotonic_ns is not None:
                raise ValueError("None generation is only valid for undispatched generation invalidation")
        elif isinstance(self.worker_generation, bool) or not isinstance(self.worker_generation, int) or self.worker_generation < 1:
            raise ValueError("worker_generation must be a positive integer")
        if self.dispatched_at_monotonic_ns is not None and (isinstance(self.dispatched_at_monotonic_ns, bool) or self.dispatched_at_monotonic_ns < 0):
            raise ValueError("dispatch monotonic time must be non-negative")
        if isinstance(self.terminal_observed_at_monotonic_ns, bool) or self.terminal_observed_at_monotonic_ns < 0:
            raise ValueError("terminal monotonic time must be non-negative")
        if self.dispatched_at_monotonic_ns is not None and self.terminal_observed_at_monotonic_ns < self.dispatched_at_monotonic_ns:
            raise ValueError("terminal time must be >= dispatch time")
        if self.terminal_at_utc.tzinfo is None or self.terminal_at_utc.utcoffset() is None:
            raise ValueError("terminal_at_utc must be UTC-aware")
        object.__setattr__(self, "normalized_provider_payload", freeze_normalized_payload(self.normalized_provider_payload))


class FakeReadWorker:
    """Deterministic replay harness; never invokes a provider."""
    def __init__(self) -> None:
        self.calls: list[ProviderReadRequest] = []

    def replay(self, request: ProviderReadRequest, outcome: ProviderExecutionOutcome,
               payload: Any = None, *, generation: int | None = 1,
               error: tuple[str, str] | None = None, diagnostic: str | None = None) -> ProviderReadOutcome:
        self.calls.append(request)
        code, message = error or (None, None)
        return ProviderReadOutcome(request.runtime_instance_id, request.provider_id, generation,
            request, outcome, generation is not None and 100 or None, 200, datetime(2026, 1, 1, tzinfo=timezone.utc), code, message, payload, diagnostic)

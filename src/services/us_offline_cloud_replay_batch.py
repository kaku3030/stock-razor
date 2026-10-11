"""Compose already-read cloud bars + upstream signals into OFFLINE Paper evidence.

Uses the source-identifying historical session reader and conservative
closed-bar fill oracle. There is deliberately no market data client,
broker adapter, scheduler, simulated-account token or order submission.
This never computes or approves a trading signal: it consumes an external
historical research decision whose provenance must be checked separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from collections.abc import Mapping

from .closed_bar_paper_replay import (
    ClosedBarResearchReceipt, HistoricalEntryBand, replay_closed_bar_long,
)
from .us_cloud_historical_session import (
    partition_historical_opend_us_15m,
    select_historical_full_60m_gate,
)


@dataclass(frozen=True)
class HistoricalReplayDecision:
    observation_id: str
    symbol: str
    closed_signal_at: datetime
    entry: HistoricalEntryBand
    upstream_hourly_passed: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.observation_id, str)
            or not 1 <= len(self.observation_id) <= 96
            or not self.observation_id.isascii()
            or any(not (x.isalnum() or x in "_-.") for x in self.observation_id)
        ):
            raise ValueError("OBSERVATION_ID_INVALID")
        if not isinstance(self.symbol, str) or not self.symbol.isascii() or not self.symbol.isalnum():
            raise ValueError("SYMBOL_INVALID")
        date = self.closed_signal_at
        if not isinstance(date, datetime) or date.tzinfo is None or date.utcoffset() is None:
            raise ValueError("DECISION_TIME_INVALID")
        object.__setattr__(self, "closed_signal_at", date.astimezone(timezone.utc))
        if not isinstance(self.entry, HistoricalEntryBand) or type(self.upstream_hourly_passed) is not bool:
            raise ValueError("REPLAY_DECISION_FIELDS_INVALID")


@dataclass(frozen=True)
class HistoricalReplayRecord:
    observation_id: str
    decision_as_of: datetime
    receipt: ClosedBarResearchReceipt


@dataclass(frozen=True)
class HistoricalReplayBatch:
    symbol: str
    session_count: int
    requested_count: int
    hypothetical_result_count: int
    no_fill_count: int
    blocked_count: int
    realized_r_not_available: bool
    hypothetical_total_r: Decimal
    hypothetical_average_r: Decimal | None
    records: tuple[HistoricalReplayRecord, ...]
    research_only: bool = True
    same_provider_source_independence_verified: bool = False
    historical_not_live: bool = True
    actual_moomoo_simulator_used: bool = False
    external_order_ids_verified: bool = False
    paper_auto_ready: bool = False
    radar_admission: str = "BLOCKED"
    live_trade: bool = False


def run_offline_cloud_replay_batch(
    quote_15m_response: Mapping[str, object],
    quote_1h_response: Mapping[str, object],
    *,
    symbol: str,
    decisions: tuple[HistoricalReplayDecision, ...],
) -> HistoricalReplayBatch:
    """Run bounded, replay-only full RTH sessions with no external IO.

    Each signal points to an exact CLOSED 15m bar_end; the 60m gate is
    selected independently as of that timestamp. Future 15m bars are
    used only to model after-entry outcomes. No strategy edge inferred.
    """
    if not isinstance(decisions, tuple) or len(decisions) > 64 or not decisions:
        raise ValueError("BATCH_SIZE_INVALID")
    if any(not isinstance(item, HistoricalReplayDecision) for item in decisions):
        raise ValueError("REPLAY_DECISION_INVALID")
    if len({x.observation_id for x in decisions}) != len(decisions):
        raise ValueError("DUPLICATE_OBSERVATION_IDS")
    sessions = partition_historical_opend_us_15m(quote_15m_response, symbol=symbol)
    records: list[HistoricalReplayRecord] = []

    for request in decisions:
        if request.symbol.upper() != symbol.upper():
            raise ValueError("CROSS_SYMBOL_DECISION")
        target = [
            (session, idx)
            for session in sessions
            for idx, bar in enumerate(session.bars)
            if bar.end == request.closed_signal_at
        ]
        if len(target) != 1:
            records.append(HistoricalReplayRecord(
                request.observation_id, request.closed_signal_at,
                ClosedBarResearchReceipt("BLOCKED", "SIGNAL_CLOSED_BAR_MISSING_OR_DUPLICATE"),
            ))
            continue
        session, signal_index = target[0]
        try:
            gate = select_historical_full_60m_gate(
                quote_1h_response, symbol=symbol,
                decision_as_of=request.closed_signal_at,
                upstream_passed=request.upstream_hourly_passed,
            )
        except (ValueError, TypeError):
            records.append(HistoricalReplayRecord(
                request.observation_id, request.closed_signal_at,
                ClosedBarResearchReceipt("BLOCKED", "60M_SOURCE_NOT_QUALIFIED"),
            ))
            continue

        receipt = replay_closed_bar_long(
            session.bars, decision_index=signal_index,
            hourly=gate, entry=request.entry,
        )
        records.append(HistoricalReplayRecord(
            request.observation_id, request.closed_signal_at, receipt,
        ))

    filled = [
        item.receipt.net_r for item in records
        if item.receipt.status == "HYPOTHETICAL_CLOSED_BAR_RESULT"
        and item.receipt.net_r is not None
    ]
    total_r = sum(filled, Decimal("0"))
    return HistoricalReplayBatch(
        symbol=symbol.upper(),
        session_count=len(sessions),
        requested_count=len(records),
        hypothetical_result_count=len(filled),
        no_fill_count=sum(x.receipt.status == "NO_FILL" for x in records),
        blocked_count=sum(x.receipt.status == "BLOCKED" for x in records),
        realized_r_not_available=True,
        hypothetical_total_r=total_r,
        hypothetical_average_r=total_r / len(filled) if filled else None,
        records=tuple(records),
    )

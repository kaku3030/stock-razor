"""Fail-closed contract for a separately reviewed external paper venue.

This module is intentionally transport-free.  It does not import an OpenD SDK,
read credentials, or submit/cancel orders.  It only proves that a caller has a
specific simulated account and a bounded, US-only paper action.  The existing
offline ExecutionEngine remains the default paper path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class ExternalSimulatorBlocked(RuntimeError):
    """Raised whenever external paper admission cannot be proven safe."""


class SimulatorMode(StrEnum):
    SIMULATE = "SIMULATE"
    REAL = "REAL"


class SoftwareStopStatus(StrEnum):
    SIM_ONLY_UNPROTECTED_IF_DISCONNECTED = "SOFTWARE_SIM_ONLY/UNPROTECTED_IF_DISCONNECTED"


@dataclass(frozen=True)
class SimulatedAccountEvidence:
    account_id: str
    observed_account_id: str
    mode: SimulatorMode | str
    observed_mode: SimulatorMode | str
    market: str
    authenticated: bool
    observed_at: datetime


@dataclass(frozen=True)
class ExternalSimOrderRequest:
    symbol: str
    side: str
    quantity: Decimal
    limit_price: Decimal
    valid_until: datetime
    kill_switch: bool = False
    protective_stop_status: SoftwareStopStatus | str = SoftwareStopStatus.SIM_ONLY_UNPROTECTED_IF_DISCONNECTED


@dataclass(frozen=True)
class ExternalSimAdmission:
    venue: str
    account_id: str
    symbol: str
    side: str
    quantity: Decimal
    limit_price: Decimal
    valid_until: datetime
    protective_stop_status: SoftwareStopStatus
    max_orders: int = 1


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExternalSimulatorBlocked(f"{field} is required")
    return value.strip()


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ExternalSimulatorBlocked(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decimal(value: object, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ExternalSimulatorBlocked(f"{field} must be a finite decimal") from exc
    if not result.is_finite() or result <= 0:
        raise ExternalSimulatorBlocked(f"{field} must be positive and finite")
    return result


def admit_external_sim_order(
    evidence: SimulatedAccountEvidence,
    request: ExternalSimOrderRequest,
    *,
    now: datetime,
    allowed_symbols: frozenset[str],
    max_order_notional: Decimal,
    max_order_quantity: Decimal,
    max_price: Decimal,
    max_orders: int = 1,
) -> ExternalSimAdmission:
    """Return a bounded SIMULATE-only admission; never calls a broker."""

    now_utc = _utc(now, "now")
    account_id = _text(evidence.account_id, "account_id")
    if account_id != _text(evidence.observed_account_id, "observed_account_id"):
        raise ExternalSimulatorBlocked("exact simulated account identity mismatch")
    if SimulatorMode(str(evidence.mode).upper()) is not SimulatorMode.SIMULATE:
        raise ExternalSimulatorBlocked("external simulator requires SIMULATE mode")
    if SimulatorMode(str(evidence.observed_mode).upper()) is not SimulatorMode.SIMULATE:
        raise ExternalSimulatorBlocked("observed account mode is not SIMULATE")
    if _text(evidence.market, "market").upper() != "US":
        raise ExternalSimulatorBlocked("external simulator contract is US-only")
    if evidence.authenticated is not True:
        raise ExternalSimulatorBlocked("simulated account authentication is not proven")
    observed_at = _utc(evidence.observed_at, "observed_at")
    if observed_at > now_utc:
        raise ExternalSimulatorBlocked("account evidence is from the future")

    symbol = _text(request.symbol, "symbol").upper()
    if symbol not in {item.upper() for item in allowed_symbols}:
        raise ExternalSimulatorBlocked("symbol is not allowlisted")
    if _text(request.side, "side").upper() not in {"BUY", "SELL"}:
        raise ExternalSimulatorBlocked("side must be BUY or SELL")
    if request.kill_switch:
        raise ExternalSimulatorBlocked("kill switch is active")
    if SoftwareStopStatus(str(request.protective_stop_status)) is not SoftwareStopStatus.SIM_ONLY_UNPROTECTED_IF_DISCONNECTED:
        raise ExternalSimulatorBlocked("protective stop status must disclose software-only protection")

    quantity = _decimal(request.quantity, "quantity")
    limit_price = _decimal(request.limit_price, "limit_price")
    expiry = _utc(request.valid_until, "valid_until")
    if expiry <= now_utc:
        raise ExternalSimulatorBlocked("paper request is expired")
    if expiry - now_utc > timedelta(minutes=15):
        raise ExternalSimulatorBlocked("paper request TTL exceeds 15 minutes")
    if max_orders != 1:
        raise ExternalSimulatorBlocked("external smoke contract permits exactly one order")
    if quantity > _decimal(max_order_quantity, "max_order_quantity"):
        raise ExternalSimulatorBlocked("quantity exceeds smoke limit")
    if limit_price > _decimal(max_price, "max_price"):
        raise ExternalSimulatorBlocked("price exceeds smoke limit")
    if quantity * limit_price > _decimal(max_order_notional, "max_order_notional"):
        raise ExternalSimulatorBlocked("notional exceeds smoke limit")

    return ExternalSimAdmission(
        venue="MOOMOO_SIMULATE_ONLY",
        account_id=account_id,
        symbol=symbol,
        side=_text(request.side, "side").upper(),
        quantity=quantity,
        limit_price=limit_price,
        valid_until=expiry,
        protective_stop_status=SoftwareStopStatus.SIM_ONLY_UNPROTECTED_IF_DISCONNECTED,
    )

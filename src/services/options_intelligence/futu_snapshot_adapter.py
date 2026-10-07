"""Normalize Futu/moomoo option snapshot rows for GEX research.

The adapter accepts plain mappings so the core options-intelligence module
does not depend on pandas or the Futu SDK. Provider I/O stays outside this
module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo

from .gex import OptionGexObservation, OptionType


@dataclass(frozen=True)
class FutuRowRejection:
    index: int
    contract_symbol: str | None
    reason: str


@dataclass(frozen=True)
class FutuGexNormalization:
    observations: tuple[OptionGexObservation, ...]
    total_rows: int
    rejected: tuple[FutuRowRejection, ...]

    @property
    def usable_rows(self) -> int:
        return len(self.observations)

    @property
    def completeness(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return self.usable_rows / self.total_rows


def _required_float(row: Mapping[str, object], field: str) -> float:
    value = row.get(field)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is missing or non-numeric") from exc
    if not isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _required_int(row: Mapping[str, object], field: str) -> int:
    value = row.get(field)
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is missing or non-integer") from exc
    return number


def _parse_option_type(value: object) -> OptionType:
    text = str(value or "").strip().upper()
    if "CALL" in text:
        return OptionType.CALL
    if "PUT" in text:
        return OptionType.PUT
    raise ValueError("option_type must identify CALL or PUT")


def _parse_expiration(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("strike_time is required")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("strike_time must be YYYY-MM-DD") from exc


def _parse_market_timestamp(
    value: object,
    *,
    market_timezone: ZoneInfo,
) -> datetime | None:
    if value in (None, "", "N/A"):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError as exc:
            raise ValueError("update_time is not a valid ISO-like timestamp") from exc
    else:
        raise ValueError("update_time has unsupported type")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=market_timezone)
    return parsed


def _contract_multiplier(row: Mapping[str, object]) -> float:
    for field in (
        "option_contract_multiplier",
        "option_contract_size",
        "lot_size",
    ):
        value = row.get(field)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(number) and number > 0:
            return number
    raise ValueError("no positive option contract multiplier is available")


def normalize_futu_snapshot_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    underlying_symbol: str,
    source: str = "futu_opend",
    quote_timezone: str = "America/New_York",
    oi_asof: datetime | None = None,
) -> FutuGexNormalization:
    """Convert Futu snapshot records to normalized GEX observations.

    Futu reports option implied volatility as a percentage value. It is
    normalized here to decimal form, for example 25.8 becomes 0.258.

    oi_asof is deliberately supplied separately because Futu exposes OI and
    quote fields in the same snapshot but does not expose a distinct OI
    timestamp in the observed payload used by STOCK RAZOR.
    """

    if not underlying_symbol.strip():
        raise ValueError("underlying_symbol is required")
    if not source.strip():
        raise ValueError("source is required")
    if oi_asof is not None and (
        oi_asof.tzinfo is None or oi_asof.utcoffset() is None
    ):
        raise ValueError("oi_asof must be timezone-aware")

    timezone = ZoneInfo(quote_timezone)
    raw_rows = list(rows)
    accepted: list[OptionGexObservation] = []
    rejected: list[FutuRowRejection] = []

    for index, row in enumerate(raw_rows):
        code = str(row.get("code") or "").strip() or None
        try:
            if row.get("option_valid") is False:
                raise ValueError("row is not a valid option snapshot")
            if code is None:
                raise ValueError("code is required")

            option_type = _parse_option_type(row.get("option_type"))
            strike = _required_float(row, "option_strike_price")
            expiration = _parse_expiration(row.get("strike_time"))
            open_interest = _required_int(row, "option_open_interest")
            gamma = _required_float(row, "option_gamma")
            multiplier = _contract_multiplier(row)

            iv_raw = row.get("option_implied_volatility")
            implied_volatility = None
            if iv_raw not in (None, "", "N/A"):
                implied_volatility = float(iv_raw) / 100.0
                if not isfinite(implied_volatility) or implied_volatility < 0:
                    raise ValueError("option_implied_volatility is invalid")

            quote_asof = _parse_market_timestamp(
                row.get("update_time"),
                market_timezone=timezone,
            )

            accepted.append(
                OptionGexObservation(
                    contract_symbol=code,
                    underlying_symbol=underlying_symbol.strip().upper(),
                    option_type=option_type,
                    strike=strike,
                    expiration=expiration,
                    open_interest=open_interest,
                    gamma=gamma,
                    contract_multiplier=multiplier,
                    source=source,
                    quote_asof=quote_asof,
                    oi_asof=oi_asof,
                    implied_volatility=implied_volatility,
                )
            )
        except (TypeError, ValueError, OverflowError) as exc:
            rejected.append(
                FutuRowRejection(
                    index=index,
                    contract_symbol=code,
                    reason=str(exc),
                )
            )

    return FutuGexNormalization(
        observations=tuple(accepted),
        total_rows=len(raw_rows),
        rejected=tuple(rejected),
    )

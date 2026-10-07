"""Gamma-exposure evidence for US Radar research.

This module intentionally emits evidence, not trade decisions.

The default signed convention is the common research approximation:
CALL gamma exposure is positive and PUT gamma exposure is negative.
That convention is an assumption about positioning, not observed dealer
inventory, and is therefore carried explicitly in every evidence object.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from math import isfinite
from typing import Iterable


class OptionType(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class GexSignConvention(StrEnum):
    CALL_POSITIVE_PUT_NEGATIVE = "CALL_POSITIVE_PUT_NEGATIVE"


@dataclass(frozen=True)
class GexAssumptionSet:
    """Explicit assumptions used to sign and scale gamma exposure."""

    sign_convention: GexSignConvention = (
        GexSignConvention.CALL_POSITIVE_PUT_NEGATIVE
    )
    price_move_fraction: float = 0.01
    dealer_inventory_observed: bool = False

    def __post_init__(self) -> None:
        if not isfinite(self.price_move_fraction) or self.price_move_fraction <= 0:
            raise ValueError("price_move_fraction must be finite and positive")
        if self.dealer_inventory_observed:
            raise ValueError(
                "GEX V0.1 does not support claiming observed dealer inventory"
            )


@dataclass(frozen=True)
class OptionGexObservation:
    """One option contract observation at current spot."""

    contract_symbol: str
    underlying_symbol: str
    option_type: OptionType
    strike: float
    expiration: date
    open_interest: int
    gamma: float
    contract_multiplier: float
    source: str
    quote_asof: datetime | None = None
    oi_asof: datetime | None = None
    implied_volatility: float | None = None

    def __post_init__(self) -> None:
        if not self.contract_symbol.strip():
            raise ValueError("contract_symbol is required")
        if not self.underlying_symbol.strip():
            raise ValueError("underlying_symbol is required")
        if not self.source.strip():
            raise ValueError("source is required")
        if not isfinite(self.strike) or self.strike <= 0:
            raise ValueError("strike must be finite and positive")
        if self.open_interest < 0:
            raise ValueError("open_interest cannot be negative")
        if not isfinite(self.gamma) or self.gamma < 0:
            raise ValueError("gamma must be finite and non-negative")
        if not isfinite(self.contract_multiplier) or self.contract_multiplier <= 0:
            raise ValueError("contract_multiplier must be finite and positive")
        if self.implied_volatility is not None and (
            not isfinite(self.implied_volatility)
            or self.implied_volatility < 0
        ):
            raise ValueError(
                "implied_volatility must be finite and non-negative when present"
            )
        for field_name, timestamp in (
            ("quote_asof", self.quote_asof),
            ("oi_asof", self.oi_asof),
        ):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True)
class StrikeGex:
    strike: float
    signed_gex: float
    absolute_gex: float
    call_gex: float
    put_gex: float
    open_interest: int
    contracts: int


@dataclass(frozen=True)
class GexEvidence:
    """Research evidence emitted to US Radar / Main Control."""

    underlying_symbol: str
    spot: float
    market_date: date
    calculated_at: datetime
    source_set: tuple[str, ...]
    assumption_set: GexAssumptionSet

    net_gex: float
    absolute_gex: float
    call_gex: float
    put_gex: float

    call_wall: float | None
    put_wall: float | None
    strongest_positive_strike: float | None
    strongest_negative_strike: float | None

    zero_dte_absolute_gex: float
    zero_dte_share: float | None

    contracts_total: int
    contracts_usable: int
    completeness: float
    strike_profile: tuple[StrikeGex, ...]

    quote_asof_min: datetime | None
    quote_asof_max: datetime | None
    oi_asof_min: datetime | None
    oi_asof_max: datetime | None

    gamma_flip: float | None
    gamma_flip_status: str
    unknown_fields: tuple[str, ...]
    warnings: tuple[str, ...]

    research_only: bool = True
    trading_authority: bool = False

    def to_payload(self) -> dict[str, object]:
        return {
            "underlying_symbol": self.underlying_symbol,
            "spot": self.spot,
            "market_date": self.market_date.isoformat(),
            "calculated_at": self.calculated_at.isoformat(),
            "source_set": list(self.source_set),
            "assumption_set": {
                "sign_convention": self.assumption_set.sign_convention.value,
                "price_move_fraction": self.assumption_set.price_move_fraction,
                "dealer_inventory_observed": (
                    self.assumption_set.dealer_inventory_observed
                ),
            },
            "options_regime": _classify_regime(self.net_gex),
            "net_gex": self.net_gex,
            "absolute_gex": self.absolute_gex,
            "call_gex": self.call_gex,
            "put_gex": self.put_gex,
            "gamma_flip": self.gamma_flip,
            "gamma_flip_status": self.gamma_flip_status,
            "call_wall": self.call_wall,
            "put_wall": self.put_wall,
            "expiry_concentration": {
                "zero_dte_absolute_gex": self.zero_dte_absolute_gex,
                "zero_dte_share": self.zero_dte_share,
            },
            "data_timestamp": self.calculated_at.isoformat(),
            "quote_asof_min": (
                self.quote_asof_min.isoformat()
                if self.quote_asof_min is not None
                else None
            ),
            "quote_asof_max": (
                self.quote_asof_max.isoformat()
                if self.quote_asof_max is not None
                else None
            ),
            "oi_asof_min": (
                self.oi_asof_min.isoformat()
                if self.oi_asof_min is not None
                else None
            ),
            "oi_asof_max": (
                self.oi_asof_max.isoformat()
                if self.oi_asof_max is not None
                else None
            ),
            "contracts_total": self.contracts_total,
            "contracts_usable": self.contracts_usable,
            "completeness": self.completeness,
            "unknown_fields": list(self.unknown_fields),
            "warnings": list(self.warnings),
            "research_only": self.research_only,
            "trading_authority": self.trading_authority,
        }


def _classify_regime(net_gex: float) -> str:
    if net_gex > 0:
        return "POSITIVE_GAMMA_ASSUMPTION"
    if net_gex < 0:
        return "NEGATIVE_GAMMA_ASSUMPTION"
    return "NEUTRAL_OR_OFFSET"


def _timestamp_range(
    values: Iterable[datetime | None],
) -> tuple[datetime | None, datetime | None]:
    known = [value for value in values if value is not None]
    if not known:
        return None, None
    return min(known), max(known)


def _signed_gex(
    observation: OptionGexObservation,
    *,
    spot: float,
    assumptions: GexAssumptionSet,
) -> float:
    magnitude = (
        observation.gamma
        * observation.open_interest
        * observation.contract_multiplier
        * spot
        * spot
        * assumptions.price_move_fraction
    )
    if (
        assumptions.sign_convention
        is GexSignConvention.CALL_POSITIVE_PUT_NEGATIVE
    ):
        return magnitude if observation.option_type is OptionType.CALL else -magnitude
    raise ValueError(f"unsupported sign convention: {assumptions.sign_convention}")


def build_gex_evidence(
    observations: Iterable[OptionGexObservation],
    *,
    spot: float,
    market_date: date,
    calculated_at: datetime,
    assumptions: GexAssumptionSet | None = None,
    source_contracts_total: int | None = None,
) -> GexEvidence:
    """Build current-spot GEX evidence from already-normalized observations.

    Gamma flip is intentionally UNKNOWN in V0.1 because a defensible flip
    requires gamma re-pricing across hypothetical spot levels rather than
    reusing current-spot gamma.
    """

    if not isfinite(spot) or spot <= 0:
        raise ValueError("spot must be finite and positive")
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise ValueError("calculated_at must be timezone-aware")

    assumption_set = assumptions or GexAssumptionSet()
    rows = list(observations)
    if not rows:
        raise ValueError("at least one option observation is required")
    total_contracts = len(rows) if source_contracts_total is None else source_contracts_total
    if total_contracts < len(rows):
        raise ValueError("source_contracts_total cannot be smaller than usable rows")
    if total_contracts <= 0:
        raise ValueError("source_contracts_total must be positive")

    underlying = rows[0].underlying_symbol.strip().upper()
    if any(row.underlying_symbol.strip().upper() != underlying for row in rows):
        raise ValueError("all observations must share the same underlying")

    strike_buckets: dict[float, dict[str, float | int]] = {}
    signed_values: list[tuple[OptionGexObservation, float]] = []

    for row in rows:
        signed = _signed_gex(row, spot=spot, assumptions=assumption_set)
        signed_values.append((row, signed))
        bucket = strike_buckets.setdefault(
            row.strike,
            {
                "signed": 0.0,
                "absolute": 0.0,
                "call": 0.0,
                "put": 0.0,
                "open_interest": 0,
                "contracts": 0,
            },
        )
        bucket["signed"] = float(bucket["signed"]) + signed
        bucket["absolute"] = float(bucket["absolute"]) + abs(signed)
        if row.option_type is OptionType.CALL:
            bucket["call"] = float(bucket["call"]) + signed
        else:
            bucket["put"] = float(bucket["put"]) + signed
        bucket["open_interest"] = int(bucket["open_interest"]) + row.open_interest
        bucket["contracts"] = int(bucket["contracts"]) + 1

    strike_profile = tuple(
        StrikeGex(
            strike=strike,
            signed_gex=float(bucket["signed"]),
            absolute_gex=float(bucket["absolute"]),
            call_gex=float(bucket["call"]),
            put_gex=float(bucket["put"]),
            open_interest=int(bucket["open_interest"]),
            contracts=int(bucket["contracts"]),
        )
        for strike, bucket in sorted(strike_buckets.items())
    )

    call_gex = sum(
        value for row, value in signed_values if row.option_type is OptionType.CALL
    )
    put_gex = sum(
        value for row, value in signed_values if row.option_type is OptionType.PUT
    )
    net_gex = call_gex + put_gex
    absolute_gex = sum(abs(value) for _, value in signed_values)

    call_candidates = [item for item in strike_profile if item.call_gex > 0]
    put_candidates = [item for item in strike_profile if item.put_gex < 0]
    positive_candidates = [item for item in strike_profile if item.signed_gex > 0]
    negative_candidates = [item for item in strike_profile if item.signed_gex < 0]

    call_wall = (
        max(call_candidates, key=lambda item: item.call_gex).strike
        if call_candidates
        else None
    )
    put_wall = (
        min(put_candidates, key=lambda item: item.put_gex).strike
        if put_candidates
        else None
    )
    strongest_positive = (
        max(positive_candidates, key=lambda item: item.signed_gex).strike
        if positive_candidates
        else None
    )
    strongest_negative = (
        min(negative_candidates, key=lambda item: item.signed_gex).strike
        if negative_candidates
        else None
    )

    zero_dte_absolute = sum(
        abs(value)
        for row, value in signed_values
        if row.expiration == market_date
    )
    zero_dte_share = (
        zero_dte_absolute / absolute_gex if absolute_gex > 0 else None
    )

    quote_min, quote_max = _timestamp_range(row.quote_asof for row in rows)
    oi_min, oi_max = _timestamp_range(row.oi_asof for row in rows)

    unknown_fields = ["gamma_flip"]
    warnings = [
        "SIGNED_GEX_USES_POSITIONING_ASSUMPTION_NOT_OBSERVED_DEALER_INVENTORY"
    ]
    if oi_min is None:
        unknown_fields.append("oi_asof")
        warnings.append("OI_ASOF_NOT_EXPLICITLY_OBSERVED")
    if quote_min is None:
        unknown_fields.append("quote_asof")
        warnings.append("QUOTE_ASOF_NOT_OBSERVED")

    return GexEvidence(
        underlying_symbol=underlying,
        spot=spot,
        market_date=market_date,
        calculated_at=calculated_at,
        source_set=tuple(sorted({row.source for row in rows})),
        assumption_set=assumption_set,
        net_gex=net_gex,
        absolute_gex=absolute_gex,
        call_gex=call_gex,
        put_gex=put_gex,
        call_wall=call_wall,
        put_wall=put_wall,
        strongest_positive_strike=strongest_positive,
        strongest_negative_strike=strongest_negative,
        zero_dte_absolute_gex=zero_dte_absolute,
        zero_dte_share=zero_dte_share,
        contracts_total=total_contracts,
        contracts_usable=len(rows),
        completeness=len(rows) / total_contracts,
        strike_profile=strike_profile,
        quote_asof_min=quote_min,
        quote_asof_max=quote_max,
        oi_asof_min=oi_min,
        oi_asof_max=oi_max,
        gamma_flip=None,
        gamma_flip_status="UNKNOWN_REPRICING_NOT_IMPLEMENTED",
        unknown_fields=tuple(unknown_fields),
        warnings=tuple(warnings),
    )

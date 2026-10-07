"""Black-Scholes gamma re-pricing for research-only GEX profiles."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, time
from math import exp, isfinite, log, pi, sqrt
from typing import Iterable
from zoneinfo import ZoneInfo

from .gex import (
    GexAssumptionSet,
    GexEvidence,
    GexSignConvention,
    OptionGexObservation,
    OptionType,
)


_SECONDS_PER_YEAR = 365.0 * 24.0 * 60.0 * 60.0


@dataclass(frozen=True)
class GammaRepricingAssumptions:
    risk_free_rate: float = 0.0
    dividend_yield: float = 0.0
    expiration_hour_local: int = 16
    expiration_minute_local: int = 0
    market_timezone: str = "America/New_York"
    spot_range_fraction: float = 0.12
    grid_points: int = 121

    def __post_init__(self) -> None:
        for name, value in (
            ("risk_free_rate", self.risk_free_rate),
            ("dividend_yield", self.dividend_yield),
            ("spot_range_fraction", self.spot_range_fraction),
        ):
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0 < self.spot_range_fraction < 1:
            raise ValueError("spot_range_fraction must be between 0 and 1")
        if self.grid_points < 3:
            raise ValueError("grid_points must be at least 3")
        if not 0 <= self.expiration_hour_local <= 23:
            raise ValueError("expiration_hour_local is invalid")
        if not 0 <= self.expiration_minute_local <= 59:
            raise ValueError("expiration_minute_local is invalid")


@dataclass(frozen=True)
class GammaProfilePoint:
    spot: float
    net_gex: float
    absolute_gex: float


@dataclass(frozen=True)
class GammaProfileEvidence:
    reference_spot: float
    calculated_at: datetime
    repricing_assumptions: GammaRepricingAssumptions
    gamma_flip: float | None
    flip_status: str
    flip_candidates: tuple[float, ...]
    points: tuple[GammaProfilePoint, ...]
    contracts_total: int
    contracts_usable: int
    completeness: float
    warnings: tuple[str, ...]

    def to_payload(self) -> dict[str, object]:
        rp = self.repricing_assumptions
        return {
            "reference_spot": self.reference_spot,
            "calculated_at": self.calculated_at.isoformat(),
            "gamma_flip": self.gamma_flip,
            "flip_status": self.flip_status,
            "flip_candidates": list(self.flip_candidates),
            "contracts_total": self.contracts_total,
            "contracts_usable": self.contracts_usable,
            "completeness": self.completeness,
            "repricing_assumptions": {
                "risk_free_rate": rp.risk_free_rate,
                "dividend_yield": rp.dividend_yield,
                "expiration_hour_local": rp.expiration_hour_local,
                "expiration_minute_local": rp.expiration_minute_local,
                "market_timezone": rp.market_timezone,
                "spot_range_fraction": rp.spot_range_fraction,
                "grid_points": rp.grid_points,
            },
            "warnings": list(self.warnings),
        }


def _normal_pdf(value: float) -> float:
    return exp(-0.5 * value * value) / sqrt(2.0 * pi)


def black_scholes_gamma(
    *,
    spot: float,
    strike: float,
    volatility: float,
    time_years: float,
    risk_free_rate: float,
    dividend_yield: float,
) -> float:
    if (
        spot <= 0
        or strike <= 0
        or volatility <= 0
        or time_years <= 0
        or not all(
            isfinite(value)
            for value in (
                spot,
                strike,
                volatility,
                time_years,
                risk_free_rate,
                dividend_yield,
            )
        )
    ):
        return 0.0

    sigma_sqrt_t = volatility * sqrt(time_years)
    d1 = (
        log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility * volatility)
        * time_years
    ) / sigma_sqrt_t
    return (
        exp(-dividend_yield * time_years)
        * _normal_pdf(d1)
        / (spot * sigma_sqrt_t)
    )


def _expiration_datetime(
    row: OptionGexObservation,
    assumptions: GammaRepricingAssumptions,
) -> datetime:
    tz = ZoneInfo(assumptions.market_timezone)
    return datetime.combine(
        row.expiration,
        time(
            assumptions.expiration_hour_local,
            assumptions.expiration_minute_local,
        ),
        tzinfo=tz,
    )


def _find_crossings(points: tuple[GammaProfilePoint, ...]) -> tuple[float, ...]:
    crossings: list[float] = []
    for left, right in zip(points, points[1:]):
        if left.net_gex == 0:
            crossings.append(left.spot)
            continue
        if right.net_gex == 0:
            crossings.append(right.spot)
            continue
        if (left.net_gex < 0 < right.net_gex) or (
            left.net_gex > 0 > right.net_gex
        ):
            weight = abs(left.net_gex) / (
                abs(left.net_gex) + abs(right.net_gex)
            )
            crossings.append(left.spot + (right.spot - left.spot) * weight)
    return tuple(dict.fromkeys(crossings))


def build_gamma_profile(
    observations: Iterable[OptionGexObservation],
    *,
    reference_spot: float,
    calculated_at: datetime,
    gex_assumptions: GexAssumptionSet | None = None,
    repricing: GammaRepricingAssumptions | None = None,
    source_contracts_total: int | None = None,
) -> GammaProfileEvidence:
    """Re-price gamma across a spot grid with frozen IV.

    This is a scenario model, not observed future gamma. It deliberately
    carries STATIC_IV_REPRICING as a warning.
    """

    if not isfinite(reference_spot) or reference_spot <= 0:
        raise ValueError("reference_spot must be finite and positive")
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise ValueError("calculated_at must be timezone-aware")

    gex = gex_assumptions or GexAssumptionSet()
    rp = repricing or GammaRepricingAssumptions()
    rows = list(observations)
    total = len(rows) if source_contracts_total is None else source_contracts_total
    if total < len(rows):
        raise ValueError("source_contracts_total cannot be smaller than input rows")

    usable: list[tuple[OptionGexObservation, float]] = []
    for row in rows:
        if row.implied_volatility is None or row.implied_volatility <= 0:
            continue
        expiry = _expiration_datetime(row, rp)
        expiry_utc = expiry.astimezone(calculated_at.tzinfo)
        seconds = (expiry_utc - calculated_at).total_seconds()
        if seconds <= 0:
            continue
        usable.append((row, seconds / _SECONDS_PER_YEAR))

    lower = reference_spot * (1.0 - rp.spot_range_fraction)
    upper = reference_spot * (1.0 + rp.spot_range_fraction)
    step = (upper - lower) / (rp.grid_points - 1)

    points: list[GammaProfilePoint] = []
    for index in range(rp.grid_points):
        scenario_spot = lower + step * index
        signed_values: list[float] = []
        for row, time_years in usable:
            gamma = black_scholes_gamma(
                spot=scenario_spot,
                strike=row.strike,
                volatility=row.implied_volatility or 0.0,
                time_years=time_years,
                risk_free_rate=rp.risk_free_rate,
                dividend_yield=rp.dividend_yield,
            )
            magnitude = (
                gamma
                * row.open_interest
                * row.contract_multiplier
                * scenario_spot
                * scenario_spot
                * gex.price_move_fraction
            )
            if (
                gex.sign_convention
                is GexSignConvention.CALL_POSITIVE_PUT_NEGATIVE
            ):
                signed = (
                    magnitude
                    if row.option_type is OptionType.CALL
                    else -magnitude
                )
            else:
                raise ValueError(
                    f"unsupported sign convention: {gex.sign_convention}"
                )
            signed_values.append(signed)

        points.append(
            GammaProfilePoint(
                spot=scenario_spot,
                net_gex=sum(signed_values),
                absolute_gex=sum(abs(value) for value in signed_values),
            )
        )

    point_tuple = tuple(points)
    crossings = _find_crossings(point_tuple) if usable else ()
    gamma_flip = (
        min(crossings, key=lambda value: abs(value - reference_spot))
        if crossings
        else None
    )
    if not usable:
        status = "UNKNOWN_NO_REPRICABLE_CONTRACTS"
    elif crossings:
        status = "ESTIMATED_STATIC_IV"
    else:
        status = "NO_CROSSING_IN_GRID"

    return GammaProfileEvidence(
        reference_spot=reference_spot,
        calculated_at=calculated_at,
        repricing_assumptions=rp,
        gamma_flip=gamma_flip,
        flip_status=status,
        flip_candidates=crossings,
        points=point_tuple,
        contracts_total=total,
        contracts_usable=len(usable),
        completeness=(len(usable) / total) if total else 0.0,
        warnings=(
            "STATIC_IV_REPRICING",
            "DEALER_POSITIONING_SIGN_IS_ASSUMED",
        ),
    )


def apply_gamma_profile(
    evidence: GexEvidence,
    profile: GammaProfileEvidence,
) -> GexEvidence:
    """Attach a qualified scenario flip estimate to current-spot evidence."""

    unknown = list(evidence.unknown_fields)
    warnings = list(evidence.warnings)
    warnings.extend(item for item in profile.warnings if item not in warnings)

    if profile.gamma_flip is not None:
        unknown = [item for item in unknown if item != "gamma_flip"]

    return replace(
        evidence,
        gamma_flip=profile.gamma_flip,
        gamma_flip_status=profile.flip_status,
        unknown_fields=tuple(unknown),
        warnings=tuple(warnings),
    )

"""Read-only US options context adapter for Stock Radar V2.

The adapter can enrich research output but cannot create or modify trading
permission. It consumes already-qualified OptionsIntelligencePacket objects;
it performs no provider I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.services.options_intelligence.contract import OptionsIntelligencePacket


def normalize_options_underlying(symbol: str) -> str:
    value = str(symbol or "").strip().upper()
    if value.startswith("US."):
        return value[3:]
    return value


@dataclass(frozen=True)
class RadarOptionsContext:
    underlying_symbol: str
    status: str
    generated_at: datetime
    age_seconds: float
    options_regime: str | None
    net_gex: float | None
    gamma_flip: float | None
    gamma_flip_status: str | None
    call_wall: float | None
    put_wall: float | None
    zero_dte_share: float | None
    freshness_status: str
    clock_status: str
    gex_completeness: float
    profile_completeness: float
    unknown_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    price_acceptance_required: bool = True
    decision_permission: str = "BLOCKED_V0_1"
    trading_authority: bool = False
    live_trade: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "underlying_symbol": self.underlying_symbol,
            "status": self.status,
            "generated_at": self.generated_at.isoformat(),
            "age_seconds": self.age_seconds,
            "options_regime": self.options_regime,
            "net_gex": self.net_gex,
            "gamma_flip": self.gamma_flip,
            "gamma_flip_status": self.gamma_flip_status,
            "call_wall": self.call_wall,
            "put_wall": self.put_wall,
            "zero_dte_share": self.zero_dte_share,
            "freshness_status": self.freshness_status,
            "clock_status": self.clock_status,
            "gex_completeness": self.gex_completeness,
            "profile_completeness": self.profile_completeness,
            "unknown_fields": list(self.unknown_fields),
            "warnings": list(self.warnings),
            "price_acceptance_required": self.price_acceptance_required,
            "decision_permission": self.decision_permission,
            "trading_authority": self.trading_authority,
            "live_trade": self.live_trade,
        }


def _regime(net_gex: float) -> str:
    if net_gex > 0:
        return "POSITIVE_GAMMA_ASSUMPTION"
    if net_gex < 0:
        return "NEGATIVE_GAMMA_ASSUMPTION"
    return "NEUTRAL_OR_OFFSET"


def build_radar_options_context(
    packet: OptionsIntelligencePacket,
    *,
    expected_underlying: str,
    observed_at: datetime,
    max_packet_age: timedelta = timedelta(minutes=15),
    max_future_skew: timedelta = timedelta(seconds=5),
) -> RadarOptionsContext:
    """Convert an options packet into bounded Radar context.

    BLOCKED options context does not block the price/technical Radar itself.
    The caller may display the context status, but must not use it to authorize
    a signal or order.
    """

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    if max_packet_age <= timedelta(0):
        raise ValueError("max_packet_age must be positive")
    if max_future_skew < timedelta(0):
        raise ValueError("max_future_skew must be non-negative")

    expected = normalize_options_underlying(expected_underlying)
    actual = normalize_options_underlying(packet.current_gex.underlying_symbol)
    age_seconds = (observed_at - packet.generated_at).total_seconds()

    warnings = list(packet.current_gex.warnings)
    warnings.extend(
        item for item in packet.gamma_profile.warnings if item not in warnings
    )
    if packet.clock_alignment is not None:
        warnings.extend(
            item
            for item in packet.clock_alignment.warnings
            if item not in warnings
        )
    warnings.extend(
        item
        for item in packet.freshness.policy_warnings
        if item not in warnings
    )

    status = packet.context_permission
    if actual != expected:
        status = "BLOCKED"
        warnings.append("OPTIONS_UNDERLYING_MISMATCH")
    elif age_seconds < -max_future_skew.total_seconds():
        status = "BLOCKED"
        warnings.append("OPTIONS_PACKET_FROM_FUTURE")
    elif age_seconds > max_packet_age.total_seconds():
        status = "BLOCKED"
        warnings.append("OPTIONS_PACKET_STALE")
    elif packet.radar_admission != "CONTEXT_ONLY":
        status = "BLOCKED"
        warnings.append("OPTIONS_PACKET_NOT_ADMITTED")
    elif packet.decision_permission != "BLOCKED_V0_1":
        status = "BLOCKED"
        warnings.append("OPTIONS_DECISION_PERMISSION_INVALID")

    current = packet.current_gex
    clock_status = (
        packet.clock_alignment.status
        if packet.clock_alignment is not None
        else "UNKNOWN"
    )
    return RadarOptionsContext(
        underlying_symbol=actual,
        status=status,
        generated_at=packet.generated_at,
        age_seconds=age_seconds,
        options_regime=_regime(current.net_gex),
        net_gex=current.net_gex,
        gamma_flip=current.gamma_flip,
        gamma_flip_status=current.gamma_flip_status,
        call_wall=current.call_wall,
        put_wall=current.put_wall,
        zero_dte_share=current.zero_dte_share,
        freshness_status=packet.freshness.status,
        clock_status=clock_status,
        gex_completeness=current.completeness,
        profile_completeness=packet.gamma_profile.completeness,
        unknown_fields=packet.unknown_fields,
        warnings=tuple(dict.fromkeys(warnings)),
    )

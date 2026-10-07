"""Evidence contract joining current GEX, freshness and gamma profile."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .gamma_profile import GammaProfileEvidence
from .gex import GexEvidence
from .qualification import GexFreshnessQualification


@dataclass(frozen=True)
class OptionsIntelligencePacket:
    schema_version: str
    generated_at: datetime
    current_gex: GexEvidence
    freshness: GexFreshnessQualification
    gamma_profile: GammaProfileEvidence

    @property
    def context_permission(self) -> str:
        if self.freshness.status == "BLOCKED":
            return "BLOCKED"
        if (
            self.freshness.status == "DEGRADED"
            or self.current_gex.completeness < 0.80
            or self.gamma_profile.completeness < 0.80
        ):
            return "DEGRADED_RESEARCH"
        return "RESEARCH_ONLY"

    @property
    def decision_permission(self) -> str:
        return "BLOCKED_V0_1"

    @property
    def radar_admission(self) -> str:
        return (
            "CONTEXT_ONLY"
            if self.context_permission != "BLOCKED"
            else "BLOCKED"
        )

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        values = list(self.current_gex.unknown_fields)
        if self.gamma_profile.gamma_flip is None and "gamma_flip" not in values:
            values.append("gamma_flip")
        return tuple(values)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "underlying_symbol": self.current_gex.underlying_symbol,
            "current_gex": self.current_gex.to_payload(),
            "freshness": self.freshness.to_payload(),
            "gamma_profile": self.gamma_profile.to_payload(),
            "context_permission": self.context_permission,
            "decision_permission": self.decision_permission,
            "radar_admission": self.radar_admission,
            "price_acceptance_required": True,
            "unknown_fields": list(self.unknown_fields),
            "trading_authority": False,
            "live_trade": False,
        }


def build_options_intelligence_packet(
    *,
    current_gex: GexEvidence,
    freshness: GexFreshnessQualification,
    gamma_profile: GammaProfileEvidence,
    generated_at: datetime,
) -> OptionsIntelligencePacket:
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    if current_gex.underlying_symbol.strip() == "":
        raise ValueError("current_gex underlying symbol is required")
    return OptionsIntelligencePacket(
        schema_version="us_options_gex.v0.1",
        generated_at=generated_at,
        current_gex=current_gex,
        freshness=freshness,
        gamma_profile=gamma_profile,
    )

"""Static provider definitions for the Self-Survival Layer.

Lifecycle observations are populated at runtime. Static capability notes must never
be interpreted as current health evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contract import ProviderRole


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    role: ProviderRole
    market_scope: tuple[str, ...]
    decision_criticality: str
    fallback_provider: str | None = None
    capability_notes: tuple[str, ...] = ()


DEFAULT_PROVIDER_REGISTRY: dict[str, ProviderDefinition] = {
    "moomoo_opend": ProviderDefinition(
        provider_id="moomoo_opend",
        role=ProviderRole.PRIMARY,
        market_scope=("US",),
        decision_criticality="CORE_MARKET_DATA",
        fallback_provider="alpaca",
        capability_notes=("US PRIMARY via persistent OpenD; cloud path must remain PC-independent.",),
    ),
    "eastmoney": ProviderDefinition(
        provider_id="eastmoney",
        role=ProviderRole.PRIMARY,
        market_scope=("CN",),
        decision_criticality="CORE_MARKET_DATA",
        fallback_provider="tencent",
        capability_notes=("A-share primary observer path.",),
    ),
    "tencent": ProviderDefinition(
        provider_id="tencent",
        role=ProviderRole.FALLBACK,
        market_scope=("CN",),
        decision_criticality="FALLBACK_MARKET_DATA",
        capability_notes=("A-share fallback requires independent timestamp/currentness qualification.",),
    ),
    "alpaca": ProviderDefinition(
        provider_id="alpaca",
        role=ProviderRole.FALLBACK,
        market_scope=("US",),
        decision_criticality="FALLBACK_MARKET_DATA",
        capability_notes=(
            "IEX read-only data can be used only when qualified.",
            "SIP entitlement must never be assumed; premium entitlement is separate.",
        ),
    ),
    "twelve_data": ProviderDefinition(
        provider_id="twelve_data",
        role=ProviderRole.FALLBACK,
        market_scope=("US", "GLOBAL"),
        decision_criticality="FALLBACK_MARKET_DATA",
        capability_notes=("Credential, quota, entitlement, and Radar use require runtime evidence.",),
    ),
    "eodhd": ProviderDefinition(
        provider_id="eodhd",
        role=ProviderRole.CROSS_CHECK,
        market_scope=("CN", "GLOBAL"),
        decision_criticality="CROSS_CHECK_DATA",
        capability_notes=(
            "Target CN ETFs do not provide 1m data.",
            "Known target CN ETF support is 5m and 1h; never advertise 1m fallback capability.",
        ),
    ),
    "openai": ProviderDefinition(
        provider_id="openai",
        role=ProviderRole.AI,
        market_scope=("AI",),
        decision_criticality="AI_ENRICHMENT",
        capability_notes=("AI failure must not stop deterministic Radar core.",),
    ),
    "anthropic": ProviderDefinition(
        provider_id="anthropic",
        role=ProviderRole.AI,
        market_scope=("AI",),
        decision_criticality="AI_ENRICHMENT",
        capability_notes=("AI failure must not stop deterministic Radar core.",),
    ),
    "tavily": ProviderDefinition(
        provider_id="tavily",
        role=ProviderRole.SEARCH,
        market_scope=("SEARCH", "NEWS"),
        decision_criticality="ENRICHMENT",
        capability_notes=("Search exhaustion must degrade enrichment explicitly, not market-data health.",),
    ),
    "aws": ProviderDefinition(
        provider_id="aws",
        role=ProviderRole.INFRA,
        market_scope=("INFRA",),
        decision_criticality="INFRA_CRITICAL",
        capability_notes=("No automatic paid upgrade, billing-limit increase, or auto recharge.",),
    ),
}


def get_provider_definition(provider_id: str) -> ProviderDefinition:
    try:
        return DEFAULT_PROVIDER_REGISTRY[provider_id]
    except KeyError as exc:
        raise KeyError(f"unknown provider_id: {provider_id}") from exc

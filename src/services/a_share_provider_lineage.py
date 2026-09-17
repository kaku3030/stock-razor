"""Provider/upstream lineage contract for A-share realtime source tokens.

Foundation A0 scope only.  This module describes identity; it does not select
providers, perform I/O, classify health/currentness, or change fallback order.

Why this exists
---------------
A runtime source token is not necessarily the same thing as either the Stock
Razor adapter or the external upstream family.  For example, ``akshare_em``
and ``efinance`` use different adapter paths but both belong to the Eastmoney
upstream family; ``tencent`` and ``akshare_qq`` currently describe the same
AkShare/Tencent realtime route even though ``TencentFetcher`` separately exists
for daily/index capabilities.

Reconciliation must know that distinction before it can count evidence as
independent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class RealtimeSourceLineage:
    """Static identity for one admitted realtime source token."""

    source_token: str
    adapter_id: str
    upstream_lineage_id: str
    endpoint_id: str
    markets: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "source_token",
            "adapter_id",
            "upstream_lineage_id",
            "endpoint_id",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            if value != value.strip():
                raise ValueError(f"{field_name} must not contain outer whitespace")
        if not self.markets or any(
            not isinstance(market, str) or not market.strip() for market in self.markets
        ):
            raise ValueError("markets must contain non-empty strings")
        if len(set(self.markets)) != len(self.markets):
            raise ValueError("markets must not contain duplicates")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["markets"] = list(self.markets)
        return payload


# Endpoint IDs are Radar semantic identifiers, not promises that an external
# URL/host will remain unchanged forever.
_CN_REALTIME_SOURCE_LINEAGE_MUTABLE = {
    "efinance": RealtimeSourceLineage(
        source_token="efinance",
        adapter_id="efinance",
        upstream_lineage_id="eastmoney",
        endpoint_id="efinance.realtime_quote",
        markets=("cn",),
    ),
    "akshare_em": RealtimeSourceLineage(
        source_token="akshare_em",
        adapter_id="akshare",
        upstream_lineage_id="eastmoney",
        endpoint_id="akshare.eastmoney_spot",
        markets=("cn",),
    ),
    "akshare_sina": RealtimeSourceLineage(
        source_token="akshare_sina",
        adapter_id="akshare",
        upstream_lineage_id="sina",
        endpoint_id="akshare.sina_spot",
        markets=("cn",),
    ),
    "akshare_qq": RealtimeSourceLineage(
        source_token="akshare_qq",
        adapter_id="akshare",
        upstream_lineage_id="tencent",
        endpoint_id="akshare.tencent_spot",
        markets=("cn",),
    ),
    "tencent": RealtimeSourceLineage(
        source_token="tencent",
        adapter_id="akshare",
        upstream_lineage_id="tencent",
        endpoint_id="akshare.tencent_spot",
        markets=("cn",),
    ),
    "tushare": RealtimeSourceLineage(
        source_token="tushare",
        adapter_id="tushare",
        upstream_lineage_id="tushare",
        endpoint_id="tushare.realtime_quote",
        markets=("cn",),
    ),
    "tickflow": RealtimeSourceLineage(
        source_token="tickflow",
        adapter_id="tickflow",
        upstream_lineage_id="tickflow",
        endpoint_id="tickflow.realtime_quote",
        markets=("cn",),
    ),
}

CN_REALTIME_SOURCE_LINEAGE: Mapping[str, RealtimeSourceLineage] = MappingProxyType(
    _CN_REALTIME_SOURCE_LINEAGE_MUTABLE
)


def get_cn_realtime_source_lineage() -> tuple[dict[str, object], ...]:
    """Return deterministic, JSON-ready lineage metadata.

    This function is deliberately side-effect free and contains no provider
    health or selection semantics.  It is suitable for later additive exposure
    by DataCapabilityService once that integration slice is reviewed.
    """

    return tuple(
        CN_REALTIME_SOURCE_LINEAGE[token].to_dict()
        for token in sorted(CN_REALTIME_SOURCE_LINEAGE)
    )

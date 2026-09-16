"""Read-only A-share source authority adapter for replay sandbox.

The adapter owns no provider registry.  It consumes the accepted A0 canonical
lineage authority and the bounded A1 intraday endpoint-extension authority.
"""
from __future__ import annotations

from src.services.a_share_intraday_semantics import CN_INTRADAY_ENDPOINT_EXTENSIONS
from src.services.a_share_provider_lineage import CN_REALTIME_SOURCE_LINEAGE

from .replay_contract import SourceAuthorityResolution


def resolve_cn_replay_source(
    source_token: str,
    endpoint_id: str,
    market: str,
) -> SourceAuthorityResolution | None:
    lineage = CN_REALTIME_SOURCE_LINEAGE.get(source_token)
    if lineage is None or market not in lineage.markets:
        return None
    allowed_endpoints = CN_INTRADAY_ENDPOINT_EXTENSIONS.get(source_token)
    if allowed_endpoints is None or endpoint_id not in allowed_endpoints:
        return None
    return SourceAuthorityResolution(
        source_token=source_token,
        endpoint_id=endpoint_id,
        market=market,
        adapter_id=lineage.adapter_id,
        upstream_lineage_id=lineage.upstream_lineage_id,
        authority_ref=(
            "a-share-a0-a1:"
            f"{source_token}:{endpoint_id}:{lineage.upstream_lineage_id}"
        ),
    )

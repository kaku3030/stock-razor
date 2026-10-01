"""Reconciliation-safe A-share realtime lineage view.

Foundation A0.2 scope only.  This module consumes an *already selected / ordered*
sequence of realtime source tokens and exposes which observations share an
external upstream lineage.  It does not choose providers, change priority,
perform I/O, assign decision weights, or classify market-data health.

The important invariant is non-compensatory identity:

    two adapter paths over one upstream family != two independent sources

Unknown lineage is fail-closed for independence: it remains visible as evidence
with ``independence_eligible=False`` rather than being silently promoted to a
new independent upstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .a_share_provider_lineage import CN_REALTIME_SOURCE_LINEAGE


@dataclass(frozen=True)
class ReconciliationSourceView:
    source_token: str
    position: int
    lineage_status: str
    adapter_id: str | None
    upstream_lineage_id: str | None
    endpoint_id: str | None
    independence_eligible: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "source_token": self.source_token,
            "position": self.position,
            "lineage_status": self.lineage_status,
            "adapter_id": self.adapter_id,
            "upstream_lineage_id": self.upstream_lineage_id,
            "endpoint_id": self.endpoint_id,
            "independence_eligible": self.independence_eligible,
        }


@dataclass(frozen=True)
class UpstreamIndependenceGroup:
    upstream_lineage_id: str
    source_tokens: tuple[str, ...]
    adapter_ids: tuple[str, ...]
    endpoint_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "upstream_lineage_id": self.upstream_lineage_id,
            "source_tokens": list(self.source_tokens),
            "adapter_ids": list(self.adapter_ids),
            "endpoint_ids": list(self.endpoint_ids),
        }


def build_cn_realtime_reconciliation_view(
    source_tokens: Sequence[str] | Iterable[str],
) -> dict[str, object]:
    """Build JSON-ready upstream-independence metadata for an existing route.

    Input order is preserved as diagnostic route position.  Duplicate tokens
    are rejected because they make route provenance ambiguous.  Unknown tokens
    remain visible but are never assigned a fabricated upstream identity.
    """

    if isinstance(source_tokens, (str, bytes)):
        raise ValueError("source_tokens must be an iterable of source-token strings")

    try:
        tokens = tuple(source_tokens)
    except TypeError as exc:
        raise ValueError("source_tokens must be iterable") from exc

    for token in tokens:
        if not isinstance(token, str) or not token.strip() or token != token.strip():
            raise ValueError("every source token must be a non-empty trimmed string")

    if len(tokens) != len(set(tokens)):
        raise ValueError("source_tokens must not contain duplicates")

    sources: list[ReconciliationSourceView] = []
    grouped: dict[str, dict[str, list[str]]] = {}

    for position, token in enumerate(tokens):
        lineage = CN_REALTIME_SOURCE_LINEAGE.get(token)
        if lineage is None:
            sources.append(
                ReconciliationSourceView(
                    source_token=token,
                    position=position,
                    lineage_status="unknown",
                    adapter_id=None,
                    upstream_lineage_id=None,
                    endpoint_id=None,
                    independence_eligible=False,
                )
            )
            continue

        sources.append(
            ReconciliationSourceView(
                source_token=token,
                position=position,
                lineage_status="known",
                adapter_id=lineage.adapter_id,
                upstream_lineage_id=lineage.upstream_lineage_id,
                endpoint_id=lineage.endpoint_id,
                independence_eligible=True,
            )
        )
        bucket = grouped.setdefault(
            lineage.upstream_lineage_id,
            {"source_tokens": [], "adapter_ids": [], "endpoint_ids": []},
        )
        bucket["source_tokens"].append(token)
        if lineage.adapter_id not in bucket["adapter_ids"]:
            bucket["adapter_ids"].append(lineage.adapter_id)
        if lineage.endpoint_id not in bucket["endpoint_ids"]:
            bucket["endpoint_ids"].append(lineage.endpoint_id)

    groups = tuple(
        UpstreamIndependenceGroup(
            upstream_lineage_id=upstream_id,
            source_tokens=tuple(values["source_tokens"]),
            adapter_ids=tuple(values["adapter_ids"]),
            endpoint_ids=tuple(values["endpoint_ids"]),
        )
        for upstream_id, values in sorted(grouped.items())
    )

    known_count = sum(source.independence_eligible for source in sources)
    unknown_tokens = tuple(
        source.source_token for source in sources if not source.independence_eligible
    )

    return {
        "market": "cn",
        "capability": "quote.realtime",
        "independence_unit": "upstream_lineage_id",
        "source_count": len(sources),
        "known_lineage_source_count": known_count,
        "independent_upstream_count": len(groups),
        "unknown_lineage_tokens": list(unknown_tokens),
        "sources": [source.to_dict() for source in sources],
        "independence_groups": [group.to_dict() for group in groups],
        "governance": {
            "unknown_lineage_independence_eligible": False,
            "shared_upstream_counts_once_for_independence": True,
            "changes_provider_selection": False,
            "decision_weighting": "NONE",
        },
    }

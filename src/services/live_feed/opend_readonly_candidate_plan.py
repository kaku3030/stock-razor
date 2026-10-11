"""Pure dry-run comparison of intended candidates with existing OpenD owner ACKs.

No quote context, SDK, subscription mutations, or trading authority. The
caller MUST NOT confuse bridge ACKs with independently proven broker state.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from data_provider.live_feed_types import SemanticStreamKey
from .opend_subscription_manager import (
    OpenDSubscriptionQuota,
    _validate_key,
)


@dataclass(frozen=True)
class ReadonlyCandidatePlan:
    status: str
    reason: str
    currently_acknowledged: tuple[str, ...] = ()
    proposed_additions: tuple[str, ...] = ()
    proposed_removals: tuple[str, ...] = ()
    evidence_scope: str = "EXISTING_BRIDGE_ACK_ONLY_NOT_PROVIDER_RECONCILIATION"
    provider_calls: int = 0
    subscription_changes: int = 0
    radar_admission: str = "BLOCKED"
    source_arbiter_admission: str = "BLOCKED"
    paper_auto_ready: bool = False
    live_trade: bool = False


def plan_readonly_subscriptions(
    owner_acknowledged: Sequence[SemanticStreamKey],
    desired: Sequence[SemanticStreamKey],
    *,
    quota: OpenDSubscriptionQuota | None = None,
    now_utc: datetime | None = None,
    max_candidates: int = 200,
) -> ReadonlyCandidatePlan:
    """Dry-run only; unknown entitlement blocks additions.

    owner_acknowledged is a runtime_bridge local acknowledgement,
    not broker-side subscription truth. Report never authorizes mutation.
    """
    try:
        prior, proposed = tuple(owner_acknowledged), tuple(desired)
    except (TypeError, ValueError):
        return ReadonlyCandidatePlan("BLOCKED", "INVALID_STREAM_LIST")
    if (
        type(max_candidates) is not int or max_candidates < 1
        or len(prior) > max_candidates or len(proposed) > max_candidates
    ):
        return ReadonlyCandidatePlan("BLOCKED", "CANDIDATE_LIMIT")
    if any(_validate_key(k) is not None for k in (*prior, *proposed)):
        return ReadonlyCandidatePlan("BLOCKED", "INVALID_STREAM_KEY")
    if len(set(prior)) != len(prior) or len(set(proposed)) != len(proposed):
        return ReadonlyCandidatePlan("BLOCKED", "DUPLICATE_STREAM_KEY")
    before, after = set(prior), set(proposed)
    add = tuple(sorted((k.symbol for k in after - before)))
    remove = tuple(sorted((k.symbol for k in before - after)))
    acknowledged = tuple(sorted(k.symbol for k in before))
    if add:
        if quota is None or quota.verified is not True:
            return ReadonlyCandidatePlan(
                "BLOCKED", "FRESH_PROVIDER_QUOTA_NOT_VERIFIED",
                acknowledged, add, remove,
            )
        if not (
            type(quota.remaining) is int
            and type(quota.total_used) is int
            and quota.remaining >= len(add)
            and quota.total_used >= 0
        ):
            return ReadonlyCandidatePlan(
                "BLOCKED", "QUOTA_INSUFFICIENT_OR_INVALID",
                acknowledged, add, remove,
            )
        observed = quota.observed_at_utc
        now = now_utc if now_utc is not None else datetime.now(timezone.utc)
        if (
            not isinstance(now, datetime) or now.tzinfo is None
            or now.utcoffset() is None
            or not isinstance(observed, datetime) or observed.tzinfo is None
            or observed.utcoffset() is None
        ):
            return ReadonlyCandidatePlan(
                "BLOCKED", "QUOTA_TIMESTAMP_MISSING",
                acknowledged, add, remove,
            )
        age = (now.astimezone(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
        if age < -5 or age > 120:
            return ReadonlyCandidatePlan(
                "BLOCKED", "QUOTA_STALE_OR_FUTURE",
                acknowledged, add, remove,
            )
    return ReadonlyCandidatePlan(
        "PLAN_ONLY" if add or remove else "NO_CHANGE_PLAN",
        "DRY_RUN_NEVER_MUTATES",
        acknowledged, add, remove,
    )

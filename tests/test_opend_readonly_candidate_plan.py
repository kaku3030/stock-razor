"""Read-only bridge ACK candidate plan tests; does not require OpenD."""
from datetime import datetime, timedelta, timezone

from data_provider.live_feed_types import SemanticStreamKey
from src.services.live_feed.opend_readonly_candidate_plan import plan_readonly_subscriptions
from src.services.live_feed.opend_subscription_manager import OpenDSubscriptionQuota

NOW = datetime(2026, 10, 11, 13, tzinfo=timezone.utc)
A = SemanticStreamKey("futu", "us", "US.AMD", "K_1M", "1m")
B = SemanticStreamKey("futu", "us", "US.NVDA", "K_1M", "1m")
C = SemanticStreamKey("futu", "us", "US.CIEN", "K_1M", "1m")


def quota(remaining=10, at=NOW):
    return OpenDSubscriptionQuota(0, remaining, at, True)


def test_same_bridge_ack_pool_is_no_change_plan_not_provider_evidence():
    result = plan_readonly_subscriptions((A, B), (B, A))
    assert result.status == "NO_CHANGE_PLAN"
    assert result.currently_acknowledged == ("US.AMD", "US.NVDA")
    assert "NOT_PROVIDER_RECONCILIATION" in result.evidence_scope
    assert result.provider_calls == result.subscription_changes == 0
    assert result.radar_admission == "BLOCKED"
    assert not result.paper_auto_ready and not result.live_trade


def test_unknown_entitlement_blocks_new_candidates_but_plans_removals():
    blocked = plan_readonly_subscriptions((A, B), (A, C))
    assert blocked.status == "BLOCKED"
    assert blocked.reason == "FRESH_PROVIDER_QUOTA_NOT_VERIFIED"
    assert blocked.proposed_additions == ("US.CIEN",)
    assert blocked.proposed_removals == ("US.NVDA",)
    removal = plan_readonly_subscriptions((A, B), (A,))
    assert removal.status == "PLAN_ONLY"
    assert removal.proposed_removals == ("US.NVDA",)


def test_new_candidates_never_invoke_adapter_even_with_verified_quota():
    result = plan_readonly_subscriptions((A,), (A, B), quota=quota(), now_utc=NOW)
    assert result.status == "PLAN_ONLY"
    assert result.proposed_additions == ("US.NVDA",)
    assert result.provider_calls == 0
    assert result.subscription_changes == 0


def test_reject_bad_quota_invalid_shape_and_stale_ack():
    bad = SemanticStreamKey("futu", "us", "US.AMD\nBAD", "K_1M", "1m")
    assert plan_readonly_subscriptions((A,), (bad,)).status == "BLOCKED"
    assert plan_readonly_subscriptions((A, A), (A,)).status == "BLOCKED"
    assert plan_readonly_subscriptions((A,), (A, B), quota=quota(0), now_utc=NOW).status == "BLOCKED"
    assert plan_readonly_subscriptions(
        (A,), (A, B), quota=quota(at=NOW-timedelta(hours=1)), now_utc=NOW
    ).reason == "QUOTA_STALE_OR_FUTURE"

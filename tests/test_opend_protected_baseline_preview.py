"""Fail-closed protected OpenD baseline preview: zero SDK/provider I/O."""
from datetime import datetime, timezone

from data_provider.live_feed_types import SemanticStreamKey
from src.services.live_feed.opend_readonly_candidate_plan import (
    plan_readonly_subscriptions,
)
from src.services.live_feed.opend_subscription_manager import OpenDSubscriptionQuota


NOW = datetime(2026, 10, 12, tzinfo=timezone.utc)
A = SemanticStreamKey("futu", "us", "US.AMD", "K_1M", "1m")
B = SemanticStreamKey("futu", "us", "US.NVDA", "K_1M", "1m")
C = SemanticStreamKey("futu", "us", "US.CIEN", "K_1M", "1m")
QUOTA = OpenDSubscriptionQuota(1, 5, NOW, True)


def test_cannot_propose_removing_any_protected_baseline_stream():
    result = plan_readonly_subscriptions(
        (A, B), (B,), protected=(A,), quota=QUOTA, now_utc=NOW
    )
    assert result.status == "BLOCKED"
    assert result.reason == "PROTECTED_BASELINE_REMOVAL"
    assert result.proposed_removals == ()
    assert result.proposed_additions == ()
    assert result.provider_calls == result.subscription_changes == 0
    assert result.radar_admission == "BLOCKED"
    assert not result.paper_auto_ready and not result.live_trade


def test_keep_baseline_and_safely_plan_unprotected_removal():
    result = plan_readonly_subscriptions(
        (A, B), (A,), protected=(A,), now_utc=NOW
    )
    assert result.status == "PLAN_ONLY"
    assert result.proposed_removals == ("US.NVDA",)
    assert result.proposed_additions == ()
    assert result.provider_calls == 0


def test_keep_baseline_and_plan_addition_only_with_external_quota():
    blocked = plan_readonly_subscriptions(
        (A,), (A, C), protected=(A,), now_utc=NOW
    )
    assert blocked.status == "BLOCKED"
    assert blocked.reason == "FRESH_PROVIDER_QUOTA_NOT_VERIFIED"
    result = plan_readonly_subscriptions(
        (A,), (A, C), protected=(A,), quota=QUOTA, now_utc=NOW
    )
    assert result.status == "PLAN_ONLY"
    assert result.proposed_additions == ("US.CIEN",)
    assert result.proposed_removals == ()
    assert result.provider_calls == result.subscription_changes == 0


def test_non_acknowledged_and_duplicate_protection_fail_closed():
    non_ack = plan_readonly_subscriptions(
        (A,), (A, B), protected=(B,), quota=QUOTA, now_utc=NOW
    )
    assert non_ack.status == "BLOCKED"
    assert non_ack.reason == "PROTECTED_STREAM_NOT_ACKNOWLEDGED"
    duplicate = plan_readonly_subscriptions(
        (A,), (A,), protected=(A, A), now_utc=NOW
    )
    assert duplicate.status == "BLOCKED"
    assert duplicate.reason == "DUPLICATE_STREAM_KEY"


def test_malformed_protection_never_results_in_plan_only():
    for protected in ((None,), ("US.AMD",), (A,) * 201):
        result = plan_readonly_subscriptions(
            (A,), (A,), protected=protected, now_utc=NOW
        )
        assert result.status == "BLOCKED"
        assert result.provider_calls == result.subscription_changes == 0


def test_embedded_aws_script_uses_original_fixed_stream_baseline():
    from pathlib import Path

    script = Path("ops/aws/install_us_opend_livefeed.sh").read_text(
        encoding="utf-8"
    )
    assert "protected=tuple(streams)" in script
    # One context is the runtime adapter; the second is an isolated, read-only
    # quota preflight before systemd can restart the service.
    assert script.count("ft.OpenQuoteContext(") == 2
    assert "AB_BLEND_OPEND_QUOTA_PREFLIGHT" in script
    assert script.index("PY_AB_BLEND_QUOTA_PREFLIGHT") < script.index(
        "systemctl daemon-reload"
    )
    assert script.count("bridge.start(streams)") == 1
    assert "ctx.unsubscribe(" not in script

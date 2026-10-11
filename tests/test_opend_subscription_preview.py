"""Dynamic Radar candidate previews must not perform subscription changes."""
from datetime import datetime, timedelta, timezone

from data_provider.live_feed_types import SemanticStreamKey
from src.services.live_feed.opend_subscription_manager import (
    OpenDSubscriptionManager, OpenDSubscriptionQuota,
)

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)
A = SemanticStreamKey("futu", "us", "US.AMD", "K_1M", "1m")
B = SemanticStreamKey("futu", "us", "US.NVDA", "K_1M", "1m")


class Owner:
    def __init__(self):
        self.calls = []

    def subscribe_streams(self, keys):
        self.calls.append(("subscribe", tuple(keys)))

    def unsubscribe_stream(self, key):
        self.calls.append(("unsubscribe", key))


def quota(remaining=4, observed=NOW):
    return OpenDSubscriptionQuota(0, remaining, observed, True)


def test_preview_never_adds_to_candidate_pool_or_calls_adapter():
    owner = Owner()
    manager = OpenDSubscriptionManager(
        owner, runtime_instance_id="same-opend-instance", now_utc=lambda: NOW
    )
    baseline = manager.snapshot()
    preview = manager.preview_candidates((A, B), quota=quota())
    assert preview.status == "PLAN_ONLY"
    assert preview.to_add == (A, B)
    assert preview.to_remove == ()
    assert preview.transport_mutations_attempted == 0
    assert preview.radar_admission == "BLOCKED"
    assert not preview.live_trade
    assert manager.snapshot() == baseline
    assert owner.calls == []


def test_existing_pool_preview_identifies_replacement_without_mutations():
    owner = Owner()
    manager = OpenDSubscriptionManager(
        owner, runtime_instance_id="same-opend-instance", now_utc=lambda: NOW
    )
    assert manager.add(A, quota=quota()).status == "APPLIED"
    old = tuple(owner.calls)
    state = manager.snapshot()
    preview = manager.preview_candidates((B,), quota=quota())
    assert preview.status == "PLAN_ONLY"
    assert preview.to_add == (B,)
    assert preview.to_remove == (A,)
    assert owner.calls == list(old)
    assert manager.snapshot() == state


def test_missing_stale_quota_and_bad_symbol_block_preview():
    owner = Owner()
    manager = OpenDSubscriptionManager(
        owner, runtime_instance_id="same-opend-instance", now_utc=lambda: NOW
    )
    assert manager.preview_candidates((A,), quota=None).status == "BLOCKED"
    assert manager.preview_candidates(
        (A,), quota=quota(observed=NOW - timedelta(hours=1))
    ).reason == "STALE_OR_FUTURE_QUOTA_OBSERVATION"
    bad = SemanticStreamKey("futu", "us", "US.AMD BAD", "K_1M", "1m")
    assert manager.preview_candidates((bad,), quota=quota()).status == "BLOCKED"
    assert owner.calls == []

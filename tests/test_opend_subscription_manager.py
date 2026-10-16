"""Offline contract tests for instance-scoped OpenD subscription orchestration."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from data_provider.live_feed_types import SemanticStreamKey
from src.services.live_feed.opend_subscription_manager import (
    HistoryWarmStartEvidence,
    OpenDSubscriptionManager,
    OpenDSubscriptionQuota,
)


NOW = datetime(2026, 10, 11, 1, 0, tzinfo=timezone.utc)
KEY_A = SemanticStreamKey("futu", "us", "US.AMD", "K_1M", "1m")
KEY_B = SemanticStreamKey("futu", "us", "US.NVDA", "K_1M", "1m")
KEY_C = SemanticStreamKey("futu", "us", "US.TSLA", "K_1M", "1m")


@dataclass
class FakeAdapter:
    subscribe_calls: list[tuple[SemanticStreamKey, ...]] = field(default_factory=list)
    unsubscribe_calls: list[SemanticStreamKey] = field(default_factory=list)
    fail_next_subscribe: bool = False

    def subscribe_streams(self, keys):
        self.subscribe_calls.append(tuple(keys))
        if self.fail_next_subscribe:
            self.fail_next_subscribe = False
            raise RuntimeError("fake transport failure")

    def unsubscribe_stream(self, key):
        self.unsubscribe_calls.append(key)


def quota(remaining: int = 8) -> OpenDSubscriptionQuota:
    return OpenDSubscriptionQuota(
        total_used=0,
        remaining=remaining,
        observed_at_utc=NOW,
        verified=True,
    )


def manager(adapter: FakeAdapter, instance: str = "runtime-a") -> OpenDSubscriptionManager:
    return OpenDSubscriptionManager(adapter, runtime_instance_id=instance, now_utc=lambda: NOW)


def test_repeated_add_remove_and_recover_are_transport_idempotent():
    adapter = FakeAdapter()
    service = manager(adapter)

    assert service.add(KEY_A, quota=quota()).status == "APPLIED"
    assert service.add(KEY_A, quota=quota()).status == "NOOP"
    assert adapter.subscribe_calls == [(KEY_A,)]

    assert service.remove(KEY_A).status == "APPLIED"
    assert service.remove(KEY_A).status == "NOOP"
    assert adapter.unsubscribe_calls == [KEY_A]

    service.add(KEY_A, quota=quota())
    assert service.recover("generation-2", quota=quota()).status == "RECOVERED"
    assert service.recover("generation-2", quota=quota()).status == "NOOP"
    assert adapter.subscribe_calls == [(KEY_A,), (KEY_A,), (KEY_A,)]


def test_quota_overflow_fails_closed_without_partial_transport_mutation():
    adapter = FakeAdapter()
    service = manager(adapter)

    result = service.update_candidates([KEY_A, KEY_B], quota=quota(remaining=1))

    assert result.status == "BLOCKED"
    assert result.reason == "QUOTA_EXCEEDED"
    assert adapter.subscribe_calls == []
    assert service.snapshot().applied == ()
    assert service.snapshot().candidate_pool == (KEY_A, KEY_B)


def test_recovery_rechecks_quota_for_the_full_new_incarnation():
    adapter = FakeAdapter()
    service = manager(adapter)
    service.update_candidates([KEY_A, KEY_B], quota=quota(remaining=2))

    blocked = service.recover("generation-2", quota=quota(remaining=1))

    assert blocked.status == "BLOCKED"
    assert blocked.reason == "QUOTA_EXCEEDED"
    assert adapter.subscribe_calls == [(KEY_A, KEY_B)]
    assert service.snapshot().last_recovery_token is None


def test_candidate_pool_and_recovery_are_isolated_per_manager_instance():
    adapter_a = FakeAdapter()
    adapter_b = FakeAdapter()
    service_a = manager(adapter_a, "runtime-a")
    service_b = manager(adapter_b, "runtime-b")

    service_a.update_candidates([KEY_A], quota=quota())
    service_b.update_candidates([KEY_B], quota=quota())
    service_a.recover("generation-a-2", quota=quota())

    assert service_a.snapshot().candidate_pool == (KEY_A,)
    assert service_b.snapshot().candidate_pool == (KEY_B,)
    assert service_b.snapshot().last_recovery_token is None
    assert adapter_a.subscribe_calls == [(KEY_A,), (KEY_A,)]
    assert adapter_b.subscribe_calls == [(KEY_B,)]


def test_missing_or_unverified_quota_does_not_mutate_provider():
    adapter = FakeAdapter()
    service = manager(adapter)

    missing = service.add(KEY_A, quota=None)
    unverified = service.update_candidates([KEY_A], quota=OpenDSubscriptionQuota(0, 8, NOW, False))

    assert missing.status == "BLOCKED"
    assert missing.reason == "QUOTA_OBSERVATION_REQUIRED"
    assert unverified.status == "BLOCKED"
    assert unverified.reason == "QUOTA_UNVERIFIED"
    assert adapter.subscribe_calls == []


def test_failed_mutation_is_unknown_until_a_new_recovery_token():
    adapter = FakeAdapter(fail_next_subscribe=True)
    service = manager(adapter)

    failed = service.add(KEY_A, quota=quota())
    blocked = service.add(KEY_B, quota=quota())
    recovered = service.recover("generation-2", quota=quota())

    assert failed.status == "UNKNOWN"
    assert failed.reason == "TRANSPORT_MUTATION_OUTCOME_UNKNOWN"
    assert blocked.status == "BLOCKED"
    assert blocked.reason == "TRANSPORT_STATE_UNKNOWN"
    assert recovered.status == "RECOVERED"
    assert adapter.subscribe_calls == [(KEY_A,), (KEY_A, KEY_B)]


def test_missing_history_evidence_does_not_promote_realtime_qualification():
    adapter = FakeAdapter()
    service = manager(adapter)

    missing = service.warm_start(KEY_A, None)
    invalid = service.warm_start(
        KEY_B,
        HistoryWarmStartEvidence(
            status="PASS",
            evidence_id=None,
            research_cache_seed_eligible=True,
        ),
    )
    passed = service.warm_start(
        KEY_C,
        HistoryWarmStartEvidence(
            status="PASS",
            evidence_id="history-sha256:abc",
            research_cache_seed_eligible=True,
        ),
    )
    snapshot = service.snapshot()

    assert missing.status == "UNKNOWN"
    assert invalid.status == "UNKNOWN"
    assert passed.status == "PASS"
    assert snapshot.realtime_qualification == "UNKNOWN"
    assert snapshot.radar_admission == "BLOCKED"
    assert snapshot.source_arbiter_admission == "BLOCKED"
    assert snapshot.live_trade is False
    assert adapter.subscribe_calls == []


def test_manager_has_no_global_unsubscribe_or_execution_surface():
    service = manager(FakeAdapter())
    assert not hasattr(service, "unsubscribe_all")
    assert not hasattr(service, "place_order")
    assert not hasattr(service, "promote_live")


def test_optional_mutation_frequency_limit_covers_recovery():
    adapter = FakeAdapter()
    clock = [NOW]
    service = OpenDSubscriptionManager(
        adapter,
        runtime_instance_id="runtime-a",
        now_utc=lambda: clock[0],
        min_mutation_interval_seconds=30,
    )

    assert service.add(KEY_A, quota=quota()).status == "APPLIED"
    assert service.recover("generation-2", quota=quota()).reason == "MUTATION_RATE_LIMITED"
    clock[0] += timedelta(seconds=30)
    assert service.recover("generation-2", quota=quota()).status == "RECOVERED"


def test_closed_session_still_allows_quota_guarded_subscription_intent():
    """Session closure does not prohibit provider *control-plane* requests.

    This is a fake owner, not proof of a real OpenD Qot_Sub ACK or new bars.
    """
    closed_time = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
    extended_key = SemanticStreamKey(
        "futu", "us", "US.XLV", "K_1M", "1m", session_mode="ALL",
    )
    owner = FakeAdapter()
    service = OpenDSubscriptionManager(
        owner, runtime_instance_id="closed-session",
        now_utc=lambda: closed_time,
    )
    fresh_quota = OpenDSubscriptionQuota(
        total_used=4, remaining=2,
        observed_at_utc=closed_time, verified=True,
    )

    planned = service.preview_candidates((extended_key,), quota=fresh_quota)
    assert planned.status == "PLAN_ONLY"
    assert planned.transport_mutations_attempted == 0
    assert owner.subscribe_calls == []

    result = service.update_candidates((extended_key,), quota=fresh_quota)
    assert result.status == "APPLIED"
    assert result.added == (extended_key,)
    assert result.transport_mutations_attempted == 1
    assert owner.subscribe_calls == [(extended_key,)]
    assert service.update_candidates(
        (extended_key,), quota=fresh_quota,
    ).status == "NOOP"
    assert service.snapshot().realtime_qualification == "UNKNOWN"
    assert service.snapshot().radar_admission == "BLOCKED"
    assert service.snapshot().live_trade is False


def test_off_session_subscription_still_requires_fresh_verified_quota():
    closed_time = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
    owner = FakeAdapter()
    service = OpenDSubscriptionManager(
        owner, runtime_instance_id="closed-session",
        now_utc=lambda: closed_time,
    )
    stale_quota = OpenDSubscriptionQuota(
        total_used=4, remaining=2,
        observed_at_utc=closed_time - timedelta(minutes=3),
        verified=True,
    )
    assert service.add(KEY_A, quota=None).reason == (
        "QUOTA_OBSERVATION_REQUIRED"
    )
    assert service.add(KEY_A, quota=stale_quota).reason == (
        "STALE_OR_FUTURE_QUOTA_OBSERVATION"
    )
    assert owner.subscribe_calls == []


def test_off_session_history_warm_start_never_qualifies_live_bars():
    key = SemanticStreamKey(
        "futu", "us", "US.VRTX", "K_1M", "1m", session_mode="ALL",
    )
    owner = FakeAdapter()
    service = manager(owner)
    result = service.warm_start(
        key, HistoryWarmStartEvidence(
            status="PASS", evidence_id="history-off-session:synthetic",
            research_cache_seed_eligible=True,
        ),
    )
    assert result.status == "PASS"
    assert result.realtime_qualification == "UNKNOWN"
    assert service.snapshot().radar_admission == "BLOCKED"
    assert service.snapshot().source_arbiter_admission == "BLOCKED"
    assert owner.subscribe_calls == []

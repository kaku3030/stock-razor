from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from data_provider.live_feed_types import SemanticStreamKey
from src.services.live_feed.tickflow_subscription_manager import TickFlowSubscriptionManager


NOW = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)
KEY_A = SemanticStreamKey("tickflow", "cn", "SH.600000", "QUOTE", "tick")
KEY_B = SemanticStreamKey("tickflow", "cn", "SZ.000001", "QUOTE", "tick")
HELD_159611 = SemanticStreamKey("tickflow", "cn", "SZ.159611", "QUOTE", "tick")
HELD_159209 = SemanticStreamKey("tickflow", "cn", "SZ.159209", "QUOTE", "tick")
OBSERVATION_518880 = SemanticStreamKey("tickflow", "cn", "SH.518880", "QUOTE", "tick")


@dataclass
class FakeTransport:
    subscribe_calls: list[tuple[SemanticStreamKey, ...]] = field(default_factory=list)
    unsubscribe_calls: list[tuple[SemanticStreamKey, ...]] = field(default_factory=list)
    subscribe_ack: bool = True
    unsubscribe_ack: bool = True

    def subscribe(self, keys):
        self.subscribe_calls.append(tuple(keys))
        return self.subscribe_ack

    def unsubscribe(self, keys):
        self.unsubscribe_calls.append(tuple(keys))
        return self.unsubscribe_ack


def test_dynamic_add_remove_requires_explicit_ack():
    transport = FakeTransport()
    service = TickFlowSubscriptionManager(transport, now_utc=lambda: NOW)

    assert service.update_candidates([KEY_A, KEY_B]).status == "APPLIED"
    assert service.update_candidates([KEY_B]).status == "APPLIED"
    assert transport.subscribe_calls == [(KEY_A, KEY_B)]
    assert transport.unsubscribe_calls == [(KEY_A,)]


def test_missing_ack_blocks_until_new_recovery_token():
    transport = FakeTransport(subscribe_ack=False)
    service = TickFlowSubscriptionManager(transport, now_utc=lambda: NOW)

    failed = service.update_candidates([KEY_A])
    blocked = service.update_candidates([KEY_B])
    transport.subscribe_ack = True
    recovered = service.recover("generation-2")

    assert failed.status == "UNKNOWN"
    assert failed.reason == "SUBSCRIPTION_ACK_NOT_VERIFIED"
    assert blocked.reason == "TRANSPORT_STATE_UNKNOWN"
    assert recovered.status == "RECOVERED"


def test_capacity_and_frequency_fail_closed_without_transport_mutation():
    transport = FakeTransport()
    clock = [NOW]
    service = TickFlowSubscriptionManager(
        transport, now_utc=lambda: clock[0], max_symbols=1, min_mutation_interval_seconds=30
    )

    assert service.update_candidates([KEY_A, KEY_B]).reason == "CANDIDATE_LIMIT"
    assert service.update_candidates([KEY_A]).status == "APPLIED"
    assert service.update_candidates([KEY_B]).reason == "MUTATION_RATE_LIMITED"
    assert transport.subscribe_calls == [(KEY_A,)]
    clock[0] += timedelta(seconds=30)
    assert service.update_candidates([KEY_B]).status == "APPLIED"


def test_invalid_provider_key_and_admission_remain_closed():
    transport = FakeTransport()
    service = TickFlowSubscriptionManager(transport, now_utc=lambda: NOW)
    invalid = SemanticStreamKey("tickflow", "cn", "600000.SH", "QUOTE", "tick")

    assert service.update_candidates([invalid]).reason == "UNSUPPORTED_TICKFLOW_STREAM_KEY"
    snap = service.snapshot()
    assert snap.realtime_qualification == "UNKNOWN"
    assert snap.radar_admission == "BLOCKED"
    assert snap.source_arbiter_admission == "BLOCKED"
    assert snap.live_trade is False


def test_observation_pool_keeps_holdings_and_adds_518880():
    transport = FakeTransport()
    service = TickFlowSubscriptionManager(transport, now_utc=lambda: NOW)

    result = service.update_candidates(
        [HELD_159611, HELD_159209, OBSERVATION_518880]
    )

    assert result.status == "APPLIED"
    assert {key.symbol for key in result.applied} == {
        "SZ.159611", "SZ.159209", "SH.518880"
    }
    assert transport.subscribe_calls == [
        (OBSERVATION_518880, HELD_159209, HELD_159611)
    ]

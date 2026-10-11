"""Malformed or ambiguous OpenD candidate symbols must never reach transport."""
from datetime import datetime, timezone

from data_provider.live_feed_types import SemanticStreamKey
from src.services.live_feed.opend_subscription_manager import (
    OpenDSubscriptionManager, OpenDSubscriptionQuota,
)

NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


class NoMutationAdapter:
    def subscribe_streams(self, keys):
        raise AssertionError("unsupported subscription was sent")

    def unsubscribe_stream(self, key):
        raise AssertionError("unsupported unsubscribe was sent")


def test_invalid_us_symbol_shapes_are_rejected_before_provider_mutation():
    manager = OpenDSubscriptionManager(
        NoMutationAdapter(), runtime_instance_id="audit", now_utc=lambda: NOW
    )
    quota = OpenDSubscriptionQuota(0, 20, NOW, True)
    for symbol in ("US.", "US..AMD", "US.AMD.", "US.AMD\\nBAD",
                   "US.AMD BAD", "US.AMD/ETF", "US.AMD "):
        key = SemanticStreamKey("futu", "us", symbol, "K_1M", "1m")
        result = manager.add(key, quota=quota)
        assert result.status == "BLOCKED"
        assert result.reason == "UNSUPPORTED_OPEND_STREAM_KEY"
        assert manager.snapshot().candidate_pool == ()
        assert manager.snapshot().applied == ()


def test_invalid_owner_clock_fails_closed_instead_of_attribute_error():
    manager = OpenDSubscriptionManager(
        NoMutationAdapter(), runtime_instance_id="audit", now_utc=lambda: None
    )
    key = SemanticStreamKey("futu", "us", "US.AMD", "K_1M", "1m")
    result = manager.add(key, quota=OpenDSubscriptionQuota(0, 1, NOW, True))
    assert result.status == "BLOCKED"
    assert result.reason == "INVALID_CLOCK"

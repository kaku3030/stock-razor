from datetime import datetime, timezone

import pytest
from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from data_provider.live_feed_types import LifecycleState, ProviderEvent, ProviderEventKind, SemanticStreamKey
from src.services.live_feed.commands import FakeProviderCommandExecutor
from src.services.live_feed.controller import LiveFeedController

pytestmark = pytest.mark.unit

KEYS = (
    SemanticStreamKey(provider_id="futu", market="HK", symbol="HK.00700", stream_type="QUOTE"),
    SemanticStreamKey(provider_id="futu", market="HK", symbol="HK.00700", stream_type="KLINE", timeframe="1M"),
)
EVENT_KINDS = tuple(ProviderEventKind)
POST_STOP_NON_DISCONNECT_KINDS = tuple(kind for kind in ProviderEventKind if kind is not ProviderEventKind.DISCONNECTED)


def _fixed_now() -> datetime:
    return datetime(2026, 9, 9, 10, 0, 0, tzinfo=timezone.utc)


class LiveFeedStateMachine(RuleBasedStateMachine):
    """Generated adversarial sequences for Slice-1 frozen invariants.

    This intentionally tests only behavior already promised by the frozen
    V0.1 contract and Slice-1 implementation. It does not invent future
    Currentness/Continuity/RecoveryCandidate/LIVE semantics.
    """

    def __init__(self) -> None:
        super().__init__()
        self.controller = LiveFeedController(
            runtime_instance_id="runtime-current",
            provider_id="futu",
            command_executor=FakeProviderCommandExecutor(),
            now_utc=_fixed_now,
        )

    def _current_event(self, kind: ProviderEventKind, *, key: SemanticStreamKey | None = None) -> ProviderEvent:
        snapshot = self.controller.snapshot()
        return ProviderEvent(
            runtime_instance_id=snapshot.runtime_instance_id,
            provider_id=snapshot.provider_id,
            controller_generation=snapshot.controller_generation,
            observed_at_utc=_fixed_now(),
            observed_at_monotonic=1.0,
            event_kind=kind,
            semantic_stream_key=key,
        )

    @rule(key=st.sampled_from(KEYS))
    def enqueue_add_desired(self, key: SemanticStreamKey) -> None:
        before = self.controller.snapshot()
        result = self.controller.request_add_desired(key)
        assert result.accepted
        assert self.controller.snapshot() is before

    @rule(key=st.sampled_from(KEYS))
    def enqueue_remove_desired(self, key: SemanticStreamKey) -> None:
        before = self.controller.snapshot()
        result = self.controller.request_remove_desired(key)
        assert result.accepted
        assert self.controller.snapshot() is before

    @rule(key=st.sampled_from(KEYS))
    def enqueue_readd_incarnation(self, key: SemanticStreamKey) -> None:
        before = self.controller.snapshot()
        result = self.controller.request_readd_incarnation(key)
        assert result.accepted
        assert self.controller.snapshot() is before

    @rule()
    def enqueue_stop(self) -> None:
        before = self.controller.snapshot()
        result = self.controller.request_stop()
        assert result.accepted
        assert self.controller.snapshot() is before

    @rule(kind=st.sampled_from(EVENT_KINDS), key=st.sampled_from(KEYS))
    def enqueue_current_provider_event(self, kind: ProviderEventKind, key: SemanticStreamKey) -> None:
        before = self.controller.snapshot()
        result = self.controller.submit_event(self._current_event(kind, key=key))
        assert result.accepted
        # Frozen concurrency invariant: ingress alone never publishes truth.
        assert self.controller.snapshot() is before

    @rule()
    def run_writer_pass(self) -> None:
        self.controller.process_pending()

    @rule(
        mismatch=st.sampled_from(("runtime", "provider", "generation")),
        kind=st.sampled_from(EVENT_KINDS),
        key=st.sampled_from(KEYS),
    )
    def stale_or_foreign_event_is_diagnostic_only(
        self, mismatch: str, kind: ProviderEventKind, key: SemanticStreamKey
    ) -> None:
        # Flush arbitrary prior generated work so this assertion isolates the
        # stale event rather than accidentally attributing earlier valid work
        # to it.
        self.controller.process_pending()
        before = self.controller.snapshot()
        fields = dict(
            runtime_instance_id=before.runtime_instance_id,
            provider_id=before.provider_id,
            controller_generation=before.controller_generation,
            observed_at_utc=_fixed_now(),
            observed_at_monotonic=1.0,
            event_kind=kind,
            semantic_stream_key=key,
        )
        if mismatch == "runtime":
            fields["runtime_instance_id"] = "runtime-stale"
            reason = "RUNTIME_INSTANCE_MISMATCH"
        elif mismatch == "provider":
            fields["provider_id"] = "foreign-provider"
            reason = "PROVIDER_MISMATCH"
        else:
            fields["controller_generation"] = before.controller_generation + 1
            reason = "CONTROLLER_GENERATION_MISMATCH"

        result = self.controller.submit_event(ProviderEvent(**fields))
        assert result.accepted
        self.controller.process_pending()
        after = self.controller.snapshot()

        assert after.lifecycle_state is before.lifecycle_state
        assert after.failure_class is before.failure_class
        assert after.stop_requested is before.stop_requested
        assert after.desired_registry_revision == before.desired_registry_revision
        assert any("STALE_PROVIDER_EVENT" in finding and reason in finding for finding in after.findings)

    @precondition(lambda self: self.controller.snapshot().stop_requested)
    @rule(kind=st.sampled_from(POST_STOP_NON_DISCONNECT_KINDS), key=st.sampled_from(KEYS))
    def post_stop_non_disconnect_event_cannot_advance_lifecycle(
        self, kind: ProviderEventKind, key: SemanticStreamKey
    ) -> None:
        self.controller.process_pending()
        before = self.controller.snapshot()
        result = self.controller.submit_event(self._current_event(kind, key=key))
        assert result.accepted
        self.controller.process_pending()
        after = self.controller.snapshot()
        assert after.lifecycle_state is before.lifecycle_state
        assert after.stop_requested is True

    @precondition(lambda self: self.controller.snapshot().stop_requested)
    @rule(key=st.sampled_from(KEYS))
    def post_stop_disconnect_resolves_cleanly(self, key: SemanticStreamKey) -> None:
        self.controller.process_pending()
        result = self.controller.submit_event(self._current_event(ProviderEventKind.DISCONNECTED, key=key))
        assert result.accepted
        self.controller.process_pending()
        after = self.controller.snapshot()
        assert after.lifecycle_state is LifecycleState.DISCONNECTED
        assert after.stop_requested is True

    @invariant()
    def live_promotion_remains_structurally_unreachable(self) -> None:
        assert self.controller.snapshot().lifecycle_state is not LifecycleState.LIVE

    @invariant()
    def published_identity_and_registry_are_coherent(self) -> None:
        snapshot = self.controller.snapshot()
        assert snapshot.runtime_instance_id == "runtime-current"
        assert snapshot.provider_id == "futu"
        assert snapshot.desired_registry_revision == snapshot.desired_registry.revision
        keys = [entry.semantic_stream_key for entry in snapshot.desired_registry.entries]
        assert len(keys) == len(set(keys))


TestLiveFeedStateMachine = LiveFeedStateMachine.TestCase
TestLiveFeedStateMachine.settings = settings(
    max_examples=75,
    stateful_step_count=40,
    deadline=None,
    derandomize=True,
)

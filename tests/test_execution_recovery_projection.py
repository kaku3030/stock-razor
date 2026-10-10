from datetime import datetime, timezone

from src.services.execution_engine import JournalEvent, OrderState
from src.services.execution_recovery_projection import (
    ExecutionRecoveryDecision,
    project_execution_recovery,
)


NOW = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)


def event(sequence, kind, intent_id="i-1", state=None):
    return JournalEvent(
        sequence,
        kind,
        intent_id,
        state,
        ("evidence-1",),
        NOW,
    )


def test_clear_projection_has_no_mutation_authority():
    snapshot = project_execution_recovery(
        [
            event(1, "VALIDATED", state=OrderState.VALIDATED),
            event(2, "SUBMITTING", state=OrderState.SUBMITTING),
            event(3, "ACCEPTED", state=OrderState.ACCEPTED),
        ]
    )

    assert snapshot.decision is ExecutionRecoveryDecision.CLEAR
    assert snapshot.intent_ids == ()
    assert snapshot.reasons == ()
    assert snapshot.mutation_allowed is False


def test_unclosed_submission_requires_manual_review():
    snapshot = project_execution_recovery(
        [
            event(1, "VALIDATED", state=OrderState.VALIDATED),
            event(2, "SUBMITTING", state=OrderState.SUBMITTING),
        ]
    )

    assert snapshot.decision is ExecutionRecoveryDecision.AMBIGUOUS_REVIEW_REQUIRED
    assert snapshot.intent_ids == ("i-1",)
    assert snapshot.reasons == ("AMBIGUOUS_SUBMISSION:i-1",)


def test_later_rejection_closes_submission_ambiguity():
    snapshot = project_execution_recovery(
        [
            event(1, "SUBMITTING", state=OrderState.SUBMITTING),
            event(2, "REJECTED", state=OrderState.REJECTED),
        ]
    )

    assert snapshot.decision is ExecutionRecoveryDecision.CLEAR


def test_unfinished_cancel_or_replace_requires_manual_review():
    cancel = project_execution_recovery(
        [
            event(1, "ACCEPTED", state=OrderState.ACCEPTED),
            event(2, "CANCEL_REQUESTED"),
        ]
    )
    replace = project_execution_recovery(
        [
            event(1, "ACCEPTED", state=OrderState.ACCEPTED),
            event(2, "REPLACE_REQUESTED"),
        ]
    )

    assert cancel.decision is ExecutionRecoveryDecision.PENDING_MUTATION_REVIEW_REQUIRED
    assert replace.decision is ExecutionRecoveryDecision.PENDING_MUTATION_REVIEW_REQUIRED
    assert cancel.intent_ids == replace.intent_ids == ("i-1",)


def test_ambiguous_submission_has_priority_over_pending_mutation():
    snapshot = project_execution_recovery(
        [
            event(1, "SUBMITTING", state=OrderState.SUBMITTING),
            event(2, "CANCEL_REQUESTED"),
        ]
    )

    assert snapshot.decision is ExecutionRecoveryDecision.AMBIGUOUS_REVIEW_REQUIRED

"""Read-only projection of execution recovery states for UI and alerts.

This module consumes an append-only execution journal only. It never reconciles,
mutates a store, retries an order, sends a notification, or authorizes trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .execution_engine import JournalEvent


class ExecutionRecoveryDecision(StrEnum):
    CLEAR = "CLEAR"
    AMBIGUOUS_REVIEW_REQUIRED = "AMBIGUOUS_REVIEW_REQUIRED"
    PENDING_MUTATION_REVIEW_REQUIRED = "PENDING_MUTATION_REVIEW_REQUIRED"


@dataclass(frozen=True)
class ExecutionRecoverySnapshot:
    decision: ExecutionRecoveryDecision
    intent_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    mutation_allowed: bool = False

    def __post_init__(self) -> None:
        if self.mutation_allowed:
            raise ValueError("execution recovery projection cannot authorize mutation")


def project_execution_recovery(
    events: Iterable[JournalEvent],
) -> ExecutionRecoverySnapshot:
    """Classify unresolved execution journal states without taking action."""

    ordered = tuple(sorted(events, key=lambda event: event.sequence))
    by_intent: dict[str, list[JournalEvent]] = {}
    for event in ordered:
        by_intent.setdefault(event.intent_id, []).append(event)

    ambiguous: set[str] = set()
    pending_mutation: set[str] = set()

    for intent_id, intent_events in by_intent.items():
        submitting = [event for event in intent_events if event.kind == "SUBMITTING"]
        if submitting:
            latest_terminal = max(
                (
                    event.sequence
                    for event in intent_events
                    if event.kind in {"ACCEPTED", "REJECTED"}
                ),
                default=-1,
            )
            if max(event.sequence for event in submitting) > latest_terminal:
                ambiguous.add(intent_id)

        for request_kind, completion_kind in (
            ("CANCEL_REQUESTED", "CANCELLED"),
            ("REPLACE_REQUESTED", "SUPERSEDED"),
        ):
            requests = [
                event for event in intent_events if event.kind == request_kind
            ]
            completions = [
                event.sequence for event in intent_events if event.kind == completion_kind
            ]
            if requests and max(request.sequence for request in requests) > max(
                completions, default=-1
            ):
                pending_mutation.add(intent_id)

    if ambiguous:
        return ExecutionRecoverySnapshot(
            ExecutionRecoveryDecision.AMBIGUOUS_REVIEW_REQUIRED,
            tuple(sorted(ambiguous)),
            tuple(
                f"AMBIGUOUS_SUBMISSION:{intent_id}"
                for intent_id in sorted(ambiguous)
            ),
        )
    if pending_mutation:
        return ExecutionRecoverySnapshot(
            ExecutionRecoveryDecision.PENDING_MUTATION_REVIEW_REQUIRED,
            tuple(sorted(pending_mutation)),
            tuple(
                f"PENDING_MUTATION:{intent_id}"
                for intent_id in sorted(pending_mutation)
            ),
        )
    return ExecutionRecoverySnapshot(
        ExecutionRecoveryDecision.CLEAR,
        (),
        (),
    )

"""Strategy Lab -- PIT / LLM contamination adversarial pack (S2, Sandbox).

Pure detection contract, stdlib only, leaf within the package. This module
is the *adjudicator* behind the permanent negative fixtures in
``tests/test_strategy_lab_pit_contamination.py``. It provides one narrow
``assess_*`` predicate per frozen contamination mode (A..N) and nothing else:
no runtime, no provider, no replay engine, no persistence, no LLM client, no
trading, no Strategy Lab engine mutation.

Every ``assess_*`` returns a ``GateResult`` whose ``passed=False`` means the
mode was **detected** -- a material point-in-time / LLM contamination leak.
That verdict is a VALIDATION HARD FAIL: it is never softened by research
score, never averaged away by model consensus, never excused by narrative.
This is a semantic statement, not a scoring system.

This module reuses STOCK RAZOR native contracts only:
- ``temporal_contract.canonical_utc_datetime`` for aware-datetime validation;
- ``validation_models.GateResult`` for the fail-closed verdict.
It does NOT import any external OSS runtime (TraderHarness / FinRobot) and
copies no external dataset.

Design rule shared by every predicate: an *unknown* or *malformed* input is
reported as contamination (fail-closed), never silently treated as clean.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Sequence

from .temporal_contract import canonical_utc_datetime
from .validation_models import GateResult


# ---------------------------------------------------------------------------
# Shared narrow helpers (private).
# ---------------------------------------------------------------------------


def _aware(name: str, value: Any) -> datetime:
    """Validate + canonicalize one aware datetime, or raise ValueError.

    Reuses the native temporal_contract rule: a naive datetime, an int/float
    epoch, a str, or a datetime whose ``utcoffset()`` is None are all
    rejected. Timezone is never assumed.
    """
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be an aware datetime, got {type(value).__name__}")
    return canonical_utc_datetime(value)


def _stamp(value: datetime) -> str:
    return value.isoformat(timespec="microseconds")


def _tokens(name: str, values: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(value) for value in values if str(value).strip())
    if not normalized:
        raise ValueError(f"{name} must be a non-empty sequence of non-blank strings")
    return normalized


def _contains_any(text: str, tokens: Sequence[str]) -> list[str]:
    return [token for token in tokens if token in text]


# ---------------------------------------------------------------------------
# A. Future bar leakage.
# ---------------------------------------------------------------------------


def assess_future_bar_leakage(*, bar_time: datetime, decision_time: datetime) -> GateResult:
    """A bar timestamped after the decision instant is a future-bar leak."""
    bar = _aware("bar_time", bar_time)
    decision = _aware("decision_time", decision_time)
    leaked = bar > decision
    return GateResult(
        gate="pit_future_bar",
        passed=not leaked,
        reason="future_bar_used" if leaked else "bar_not_after_decision",
        evidence={"bar_time": _stamp(bar), "decision_time": _stamp(decision)},
    )


# ---------------------------------------------------------------------------
# B. Future announcement / publication leakage.
# ---------------------------------------------------------------------------


def assess_future_publication_leakage(
    *, publication_time: datetime, decision_time: datetime
) -> GateResult:
    """An announcement published after the decision instant is future leakage."""
    publication = _aware("publication_time", publication_time)
    decision = _aware("decision_time", decision_time)
    leaked = publication > decision
    return GateResult(
        gate="pit_future_publication",
        passed=not leaked,
        reason="future_publication_used" if leaked else "publication_not_after_decision",
        evidence={
            "publication_time": _stamp(publication),
            "decision_time": _stamp(decision),
        },
    )


# ---------------------------------------------------------------------------
# C. Historical date recognition leakage.
# ---------------------------------------------------------------------------


def assess_historical_date_recognition_leakage(
    *, prompt_text: str, sensitive_dates: Sequence[str]
) -> GateResult:
    """ADVERSARIAL/FIXTURE predicate (not a universal production rule).

    Detects an LLM prompt containing an evaluation-window absolute date -- a
    recognition leak where the model can recall the day's known outcome. This
    is a deliberately narrow, string-matching fixture: it proves the *shape*
    of the leak for adversarial regression, not a context-aware production
    contamination policy. Stronger context-aware semantics (if any exist
    elsewhere) remain the production authority.
    """
    text = str(prompt_text)
    dates = _tokens("sensitive_dates", sensitive_dates)
    hits = _contains_any(text, dates)
    return GateResult(
        gate="pit_historical_date_recognition",
        passed=not hits,
        reason="absolute_date_present" if hits else "no_absolute_date",
        evidence={"matched_dates": hits},
    )


# ---------------------------------------------------------------------------
# D. Company / entity recognition leakage.
# ---------------------------------------------------------------------------


def assess_entity_recognition_leakage(
    *, prompt_text: str, masked_entities: Sequence[str]
) -> GateResult:
    """ADVERSARIAL/FIXTURE predicate (not a universal production rule).

    Detects an unmasked real entity in an LLM prompt via exact string match.
    Narrow fixture proving the leak shape for adversarial regression only; it
    is not a context-aware production contamination policy.
    """
    text = str(prompt_text)
    entities = _tokens("masked_entities", masked_entities)
    hits = _contains_any(text, entities)
    return GateResult(
        gate="pit_entity_recognition",
        passed=not hits,
        reason="unmasked_entity_present" if hits else "no_unmasked_entity",
        evidence={"matched_entities": hits},
    )


# ---------------------------------------------------------------------------
# E. report_period treated as publication_time.
# ---------------------------------------------------------------------------


def assess_report_period_as_publication(
    *,
    report_period: datetime,
    publication_time: datetime,
    decision_time: datetime,
    evidence_visible: bool,
) -> GateResult:
    """Reject the misuse of report_period AS IF it were availability time.

    The forbidden condition is treating a report period (e.g. fiscal quarter
    end) as the instant the evidence becomes usable. The correct availability
    gate is ``publication_time``, never ``report_period``:

    * ``publication_time > decision_time`` AND the evidence is presented as
      visible to the decision  => HARD FAIL (future publication leaked).
    * ``publication_time <= decision_time`` => allowed, *independent of
      report_period* (report_period is NOT required to equal publication_time,
      and report_period may even post-date publication_time without being a
      leak by itself).

    ``report_period`` is carried only as evidence provenance; it is never
    converted into a publication instant. ``evidence_visible`` is the caller's
    claim that the evidence was made available to the decision context; an
    unknown/malformed ``evidence_visible`` fails closed (contamination).
    """
    period = _aware("report_period", report_period)
    publication = _aware("publication_time", publication_time)
    decision = _aware("decision_time", decision_time)
    if not isinstance(evidence_visible, bool):
        # Unknown availability claim is fail-closed, never treated as clean.
        return GateResult(
            gate="pit_report_period_as_publication",
            passed=False,
            reason="evidence_visibility_unknown",
            evidence={
                "report_period": _stamp(period),
                "publication_time": _stamp(publication),
                "decision_time": _stamp(decision),
                "evidence_visible": evidence_visible,
            },
        )
    leaked = evidence_visible and publication > decision
    return GateResult(
        gate="pit_report_period_as_publication",
        passed=not leaked,
        reason="future_publication_visible" if leaked else "publication_not_future_or_not_visible",
        evidence={
            "report_period": _stamp(period),
            "publication_time": _stamp(publication),
            "decision_time": _stamp(decision),
            "evidence_visible": evidence_visible,
        },
    )


# ---------------------------------------------------------------------------
# F. nearest(abs(target - date)) selecting future data.
# ---------------------------------------------------------------------------


def assess_nearest_abs_future_selection(
    *, target_date: datetime, candidate_dates: Sequence[datetime]
) -> GateResult:
    """Nearest-by-absolute-distance selection that lands on a future candidate
    is a look-ahead: only candidates at-or-before the target may be chosen."""
    target = _aware("target_date", target_date)
    candidates = [_aware("candidate_dates", c) for c in candidate_dates]
    if not candidates:
        raise ValueError("candidate_dates must be non-empty")
    nearest = min(candidates, key=lambda c: abs((c - target).total_seconds()))
    leaked = nearest > target
    return GateResult(
        gate="pit_nearest_abs_future",
        passed=not leaked,
        reason="future_candidate_selected" if leaked else "candidate_not_future",
        evidence={"target_date": _stamp(target), "nearest_candidate": _stamp(nearest)},
    )


# ---------------------------------------------------------------------------
# G. Symmetric +/-N-day window leaking future data.
# ---------------------------------------------------------------------------


def assess_symmetric_window_future_leakage(
    *, center: datetime, radius: timedelta, decision_time: datetime
) -> GateResult:
    """A symmetric window [center - radius, center + radius] whose right edge
    crosses the decision instant leaks future data."""
    c = _aware("center", center)
    decision = _aware("decision_time", decision_time)
    if not isinstance(radius, timedelta):
        raise ValueError("radius must be a timedelta")
    if radius < timedelta(0):
        raise ValueError("radius must be non-negative")
    right_edge = c + radius
    leaked = right_edge > decision
    return GateResult(
        gate="pit_symmetric_window_future",
        passed=not leaked,
        reason="window_crosses_decision" if leaked else "window_within_decision",
        evidence={"right_edge": _stamp(right_edge), "decision_time": _stamp(decision)},
    )


# ---------------------------------------------------------------------------
# H. latest financials used for historical replay.
# ---------------------------------------------------------------------------


def assess_latest_financials_for_replay(
    *, financials_as_of: datetime, replay_decision_time: datetime
) -> GateResult:
    """Feeding financials as-of a later date into a replay decision is leakage."""
    as_of = _aware("financials_as_of", financials_as_of)
    decision = _aware("replay_decision_time", replay_decision_time)
    leaked = as_of > decision
    return GateResult(
        gate="pit_latest_financials_replay",
        passed=not leaked,
        reason="future_financials_used" if leaked else "financials_not_future",
        evidence={
            "financials_as_of": _stamp(as_of),
            "replay_decision_time": _stamp(decision),
        },
    )


# ---------------------------------------------------------------------------
# I. timezone-naive epoch conversion.
# ---------------------------------------------------------------------------


def assess_timezone_naive_epoch(*, value: Any) -> GateResult:
    """A naive datetime, epoch int/float, or bare string is an ambiguous-clock
    contamination: it must be rejected, never silently localized."""
    try:
        _aware("value", value)
        contaminated = False
    except (ValueError, TypeError):
        contaminated = True
    return GateResult(
        gate="pit_timezone_naive_epoch",
        passed=not contaminated,
        reason="naive_or_epoch_value" if contaminated else "aware_datetime",
        evidence={"value_type": type(value).__name__},
    )


# ---------------------------------------------------------------------------
# J. unseeded random sampling.
# ---------------------------------------------------------------------------


def assess_unseeded_random(*, seed: Any) -> GateResult:
    """Random sampling without an explicit seed breaks deterministic replay."""
    unseeded = seed is None
    return GateResult(
        gate="pit_unseeded_random",
        passed=not unseeded,
        reason="seed_missing" if unseeded else "seed_present",
        evidence={"seed_provided": seed is not None},
    )


# ---------------------------------------------------------------------------
# K. prompt metadata revealing evaluation window.
# ---------------------------------------------------------------------------


def assess_prompt_metadata_window_leakage(
    *, prompt_text: str, sensitive_dates: Sequence[str]
) -> GateResult:
    """Prompt metadata carrying the evaluation window's boundary dates is a
    leakage clue the model can exploit."""
    text = str(prompt_text)
    dates = _tokens("sensitive_dates", sensitive_dates)
    hits = _contains_any(text, dates)
    return GateResult(
        gate="pit_prompt_metadata_window",
        passed=not hits,
        reason="window_metadata_present" if hits else "no_window_metadata",
        evidence={"matched_dates": hits},
    )


# ---------------------------------------------------------------------------
# L. tool output leaking unmasked ticker/date.
# ---------------------------------------------------------------------------


def assess_tool_output_unmasked_leakage(
    *,
    tool_output: str,
    masked_entities: Sequence[str],
    sensitive_dates: Sequence[str],
) -> GateResult:
    """Tool output that surfaces an unmasked entity or an absolute date to the
    agent is a contamination leak."""
    text = str(tool_output)
    entities = _tokens("masked_entities", masked_entities)
    dates = _tokens("sensitive_dates", sensitive_dates)
    entity_hits = _contains_any(text, entities)
    date_hits = _contains_any(text, dates)
    leaked = bool(entity_hits or date_hits)
    return GateResult(
        gate="pit_tool_output_unmasked",
        passed=not leaked,
        reason="unmasked_entity_or_date" if leaked else "tool_output_clean",
        evidence={"matched_entities": entity_hits, "matched_dates": date_hits},
    )


# ---------------------------------------------------------------------------
# M. benchmark-window memorization clue.
# ---------------------------------------------------------------------------


def assess_benchmark_window_memorization(
    *, prompt_text: str, benchmark_constituents: Sequence[str]
) -> GateResult:
    """ADVERSARIAL/FIXTURE predicate (not a universal production rule).

    Detects a prompt naming benchmark constituents of the evaluation window
    via exact string match -- a memorization clue shape for adversarial
    regression only, not a context-aware production contamination policy.
    """
    text = str(prompt_text)
    constituents = _tokens("benchmark_constituents", benchmark_constituents)
    hits = _contains_any(text, constituents)
    return GateResult(
        gate="pit_benchmark_memorization",
        passed=not hits,
        reason="benchmark_constituent_present" if hits else "no_benchmark_clue",
        evidence={"matched_constituents": hits},
    )


# ---------------------------------------------------------------------------
# N. replay / cassette tamper or contract-version mismatch.
# ---------------------------------------------------------------------------


def assess_replay_tamper(
    *,
    cassette_sha256: str,
    expected_sha256: str,
    contract_version: str,
    expected_contract_version: str,
) -> GateResult:
    """A replay cassette whose content hash or prompt-contract version differs
    from its recorded manifest is tampered or version-mismatched."""
    sha_mismatch = str(cassette_sha256) != str(expected_sha256)
    version_mismatch = str(contract_version) != str(expected_contract_version)
    leaked = sha_mismatch or version_mismatch
    reason = (
        "cassette_hash_mismatch"
        if sha_mismatch
        else ("contract_version_mismatch" if version_mismatch else "replay_integrity_ok")
    )
    return GateResult(
        gate="pit_replay_tamper",
        passed=not leaked,
        reason=reason,
        evidence={
            "sha_match": not sha_mismatch,
            "version_match": not version_mismatch,
        },
    )

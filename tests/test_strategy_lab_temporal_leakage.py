from __future__ import annotations

from typing import Sequence

import pytest

from src.services.strategy_lab.temporal_leakage import (
    StartupSensitivityStatus,
    TemporalAuditFindingCode,
    TemporalLeakageStatus,
    audit_prefix_invariance,
    audit_startup_history_sensitivity,
    temporal_leakage_gate_result,
)


def _rolling_mean(rows: Sequence[float]) -> list[dict[str, float]]:
    outputs: list[dict[str, float]] = []
    for index in range(len(rows)):
        window = rows[max(0, index - 2) : index + 1]
        outputs.append({"feature": sum(window) / len(window)})
    return outputs


def _whole_series_mean(rows: Sequence[float]) -> list[dict[str, float]]:
    mean = sum(rows) / len(rows)
    return [{"feature": mean} for _ in rows]


def _next_row_signal(rows: Sequence[float]) -> list[dict[str, bool | None]]:
    outputs: list[dict[str, bool | None]] = []
    for index, value in enumerate(rows):
        if index + 1 >= len(rows):
            outputs.append({"next_up": None})
        else:
            outputs.append({"next_up": rows[index + 1] > value})
    return outputs


def _cumulative_mean(rows: Sequence[float]) -> list[dict[str, float]]:
    outputs: list[dict[str, float]] = []
    total = 0.0
    for index, value in enumerate(rows):
        total += value
        outputs.append({"feature": total / (index + 1)})
    return outputs


def test_causal_rolling_feature_is_prefix_invariant() -> None:
    report = audit_prefix_invariance(
        history=(1.0, 2.0, 4.0, 8.0, 16.0, 32.0),
        evaluator=_rolling_mean,
        cutoffs=(2, 3, 4),
    )

    assert report.status is TemporalLeakageStatus.PASS
    assert report.requested_cutoffs == (2, 3, 4)
    assert report.audited_cutoffs == (2, 3, 4)
    assert report.findings == ()
    assert temporal_leakage_gate_result(report).passed is True


def test_whole_series_aggregate_is_detected_as_future_dependent() -> None:
    report = audit_prefix_invariance(
        history=(1.0, 2.0, 4.0, 8.0, 16.0),
        evaluator=_whole_series_mean,
        cutoffs=(1, 2, 3),
    )

    assert report.status is TemporalLeakageStatus.LEAKAGE_DETECTED
    assert report.audited_cutoffs == (1, 2, 3)
    assert {finding.code for finding in report.findings} == {
        TemporalAuditFindingCode.OUTPUT_CHANGED_WITH_FUTURE_TAIL
    }
    assert all(finding.changed_fields == ("feature",) for finding in report.findings)
    gate = temporal_leakage_gate_result(report)
    assert gate.passed is False
    assert gate.reason == "implementation_future_dependency_detected"


def test_next_row_signal_equivalent_to_negative_shift_is_detected() -> None:
    report = audit_prefix_invariance(
        history=(10.0, 12.0, 11.0, 15.0, 14.0),
        evaluator=_next_row_signal,
        cutoffs=(0, 1, 2, 3),
    )

    assert report.status is TemporalLeakageStatus.LEAKAGE_DETECTED
    assert len(report.findings) == 4
    assert all(
        finding.code is TemporalAuditFindingCode.OUTPUT_CHANGED_WITH_FUTURE_TAIL
        for finding in report.findings
    )


def test_nondeterministic_full_baseline_is_indeterminate_not_lookahead() -> None:
    calls = 0

    def toggles(rows: Sequence[float]):
        nonlocal calls
        calls += 1
        delta = float(calls % 2)
        return [{"feature": value + delta} for value in rows]

    report = audit_prefix_invariance(
        history=(1.0, 2.0, 3.0, 4.0),
        evaluator=toggles,
        cutoffs=(1, 2),
    )

    assert report.status is TemporalLeakageStatus.INDETERMINATE
    assert report.audited_cutoffs == ()
    assert report.findings[0].code is TemporalAuditFindingCode.NONDETERMINISTIC_EVALUATOR
    assert report.findings[0].changed_fields == ("feature",)
    gate = temporal_leakage_gate_result(report)
    assert gate.passed is False
    assert gate.reason == "implementation_leakage_audit_indeterminate"


def test_nondeterministic_prefix_is_not_mislabeled_as_future_dependency() -> None:
    calls_by_length: dict[int, int] = {}

    def unstable_only_on_short_windows(rows: Sequence[float]):
        length = len(rows)
        calls_by_length[length] = calls_by_length.get(length, 0) + 1
        delta = 0.0 if length == 5 else float(calls_by_length[length] % 2)
        return [{"feature": value + delta} for value in rows]

    report = audit_prefix_invariance(
        history=(1.0, 2.0, 3.0, 4.0, 5.0),
        evaluator=unstable_only_on_short_windows,
        cutoffs=(2, 3),
    )

    assert report.status is TemporalLeakageStatus.INDETERMINATE
    assert report.audited_cutoffs == ()
    assert {finding.code for finding in report.findings} == {
        TemporalAuditFindingCode.NONDETERMINISTIC_EVALUATOR
    }
    assert temporal_leakage_gate_result(report).passed is False


def test_evaluator_contract_failure_is_indeterminate_and_fails_closed() -> None:
    def missing_last_output(rows: Sequence[float]):
        return [{"feature": value} for value in rows[:-1]]

    report = audit_prefix_invariance(
        history=(1.0, 2.0, 3.0, 4.0),
        evaluator=missing_last_output,
        cutoffs=(1, 2),
    )

    assert report.status is TemporalLeakageStatus.INDETERMINATE
    assert report.audited_cutoffs == ()
    assert report.findings[0].code is TemporalAuditFindingCode.OUTPUT_LENGTH_MISMATCH
    gate = temporal_leakage_gate_result(report)
    assert gate.passed is False
    assert gate.reason == "implementation_leakage_audit_indeterminate"


def test_nonfinite_snapshot_is_indeterminate_not_false_pass() -> None:
    def nonfinite(rows: Sequence[float]):
        return [{"feature": float("nan")} for _ in rows]

    report = audit_prefix_invariance(
        history=(1.0, 2.0, 3.0),
        evaluator=nonfinite,
        cutoffs=(1,),
    )

    assert report.status is TemporalLeakageStatus.INDETERMINATE
    assert report.findings[0].code is TemporalAuditFindingCode.OUTPUT_CONTRACT_ERROR


def test_final_row_cannot_be_used_as_vacuous_prefix_audit() -> None:
    with pytest.raises(ValueError, match="leave at least one future row"):
        audit_prefix_invariance(
            history=(1.0, 2.0, 3.0),
            evaluator=_rolling_mean,
            cutoffs=(2,),
        )


def test_fixed_rolling_window_is_stable_across_sufficient_startup_histories() -> None:
    report = audit_startup_history_sensitivity(
        history=(1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0),
        evaluator=_rolling_mean,
        target_index=6,
        history_lengths=(3, 4, 7),
    )

    assert report.status is StartupSensitivityStatus.STABLE
    assert report.audited_history_lengths == (3, 4, 7)
    assert report.findings == ()


def test_recursive_startup_dependency_is_diagnosed_separately_from_lookahead() -> None:
    report = audit_startup_history_sensitivity(
        history=(1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0),
        evaluator=_cumulative_mean,
        target_index=6,
        history_lengths=(2, 4, 7),
    )

    assert report.status is StartupSensitivityStatus.SENSITIVITY_DETECTED
    assert report.audited_history_lengths == (2, 4, 7)
    assert all(
        finding.code is TemporalAuditFindingCode.OUTPUT_CHANGED_WITH_STARTUP_HISTORY
        for finding in report.findings
    )


def test_nondeterministic_startup_reference_is_indeterminate_not_sensitivity() -> None:
    calls = 0

    def toggles(rows: Sequence[float]):
        nonlocal calls
        calls += 1
        delta = float(calls % 2)
        return [{"feature": value + delta} for value in rows]

    report = audit_startup_history_sensitivity(
        history=(1.0, 2.0, 3.0, 5.0, 8.0),
        evaluator=toggles,
        target_index=4,
        history_lengths=(2, 3, 5),
    )

    assert report.status is StartupSensitivityStatus.INDETERMINATE
    assert report.audited_history_lengths == ()
    assert report.findings[0].code is TemporalAuditFindingCode.NONDETERMINISTIC_EVALUATOR


def test_duplicate_cutoffs_and_history_lengths_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        audit_prefix_invariance(
            history=(1.0, 2.0, 3.0, 4.0),
            evaluator=_rolling_mean,
            cutoffs=(1, 1),
        )

    with pytest.raises(ValueError, match="duplicates"):
        audit_startup_history_sensitivity(
            history=(1.0, 2.0, 3.0, 4.0),
            evaluator=_rolling_mean,
            target_index=3,
            history_lengths=(2, 2),
        )

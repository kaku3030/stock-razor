from datetime import datetime, timedelta, timezone
from typing import Callable

import pytest

from src.services.strategy_lab import GateResult
from src.services.strategy_lab.adversarial_checks import (
    assess_benchmark_alpha,
    assess_cost_robustness,
    assess_edge_concentration,
    assess_no_lookahead,
    assess_parameter_stability,
)
from src.services.strategy_lab.temporal_leakage import (
    TemporalLeakageStatus,
    audit_prefix_invariance,
    temporal_leakage_gate_result,
)


PERMANENT_ADVERSARIAL_CASE_IDS = (
    "lookahead",
    "parameter_overfit",
    "concentrated_edge",
    "cost_fragile",
    "beta_disguised_as_alpha",
)

EXPECTED_GATES = {
    "lookahead": "lookahead",
    "parameter_overfit": "parameter_stability",
    "concentrated_edge": "edge_concentration",
    "cost_fragile": "cost_robustness",
    "beta_disguised_as_alpha": "benchmark_alpha",
}


def _bad_cases() -> dict[str, Callable[[], GateResult]]:
    confirmed_at = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    benchmark = (-0.02, 0.01, 0.03, -0.01, 0.02, -0.03)
    return {
        "lookahead": lambda: assess_no_lookahead(
            signal_confirmed_at=confirmed_at,
            latest_input_at=confirmed_at + timedelta(minutes=15),
        ),
        "parameter_overfit": lambda: assess_parameter_stability(
            selected_score=100.0,
            neighboring_scores=(-10.0, -5.0, -2.0, -8.0),
            minimum_neighbor_score_ratio=0.8,
            minimum_stable_neighbor_fraction=0.75,
        ),
        "concentrated_edge": lambda: assess_edge_concentration(
            trade_pnls=(-1.0,) * 99 + (200.0,),
            top_fraction=0.01,
            maximum_top_contribution_ratio=0.5,
        ),
        "cost_fragile": lambda: assess_cost_robustness(
            baseline_profit=100.0,
            stressed_profit=-1.0,
            minimum_retained_profit_ratio=0.5,
        ),
        "beta_disguised_as_alpha": lambda: assess_benchmark_alpha(
            strategy_returns=tuple(1.2 * value for value in benchmark),
            benchmark_returns=benchmark,
            maximum_abs_alpha_for_beta_only=0.0001,
            minimum_abs_beta_for_beta_only=0.8,
        ),
    }


def _control_cases() -> dict[str, Callable[[], GateResult]]:
    confirmed_at = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    benchmark = (-0.02, 0.01, 0.03, -0.01, 0.02, -0.03)
    return {
        "lookahead": lambda: assess_no_lookahead(
            signal_confirmed_at=confirmed_at,
            latest_input_at=confirmed_at,
        ),
        "parameter_overfit": lambda: assess_parameter_stability(
            selected_score=100.0,
            neighboring_scores=(92.0, 88.0, 95.0, 85.0),
            minimum_neighbor_score_ratio=0.8,
            minimum_stable_neighbor_fraction=0.75,
        ),
        "concentrated_edge": lambda: assess_edge_concentration(
            trade_pnls=(1.0,) * 100,
            top_fraction=0.01,
            maximum_top_contribution_ratio=0.5,
        ),
        "cost_fragile": lambda: assess_cost_robustness(
            baseline_profit=100.0,
            stressed_profit=70.0,
            minimum_retained_profit_ratio=0.5,
        ),
        "beta_disguised_as_alpha": lambda: assess_benchmark_alpha(
            strategy_returns=tuple(0.01 + 0.2 * value for value in benchmark),
            benchmark_returns=benchmark,
            maximum_abs_alpha_for_beta_only=0.0001,
            minimum_abs_beta_for_beta_only=0.8,
        ),
    }


def test_permanent_adversarial_manifest_cannot_shrink() -> None:
    assert tuple(_bad_cases()) == PERMANENT_ADVERSARIAL_CASE_IDS
    assert tuple(_control_cases()) == PERMANENT_ADVERSARIAL_CASE_IDS
    assert tuple(EXPECTED_GATES) == PERMANENT_ADVERSARIAL_CASE_IDS


@pytest.mark.parametrize("case_id", PERMANENT_ADVERSARIAL_CASE_IDS)
def test_known_bad_strategy_cannot_escape(case_id: str) -> None:
    result = _bad_cases()[case_id]()

    assert result.gate == EXPECTED_GATES[case_id]
    assert result.passed is False, f"known cheating strategy escaped validation: {case_id}"


@pytest.mark.parametrize("case_id", PERMANENT_ADVERSARIAL_CASE_IDS)
def test_control_case_can_proceed(case_id: str) -> None:
    result = _control_cases()[case_id]()

    assert result.gate == EXPECTED_GATES[case_id]
    assert result.passed is True, f"valid control was rejected: {case_id}"


def test_permanent_lookahead_case_catches_implementation_future_access() -> None:
    """Timestamp honesty alone must not let a future-dependent implementation pass."""

    def uses_whole_future(rows: tuple[float, ...]):
        mean = sum(rows) / len(rows)
        return ({"feature": mean},) * len(rows)

    report = audit_prefix_invariance(
        history=(1.0, 2.0, 4.0, 8.0, 16.0),
        evaluator=uses_whole_future,
        cutoffs=(1, 2, 3),
    )
    result = temporal_leakage_gate_result(report)

    assert report.status is TemporalLeakageStatus.LEAKAGE_DETECTED
    assert result.gate == "lookahead"
    assert result.passed is False
    assert result.reason == "implementation_future_dependency_detected"


@pytest.mark.parametrize(
    "invalid_check",
    (
        lambda: assess_parameter_stability(
            selected_score=1.0,
            neighboring_scores=(),
            minimum_neighbor_score_ratio=0.8,
            minimum_stable_neighbor_fraction=0.75,
        ),
        lambda: assess_edge_concentration(
            trade_pnls=(1.0, 2.0),
            top_fraction=0.0,
            maximum_top_contribution_ratio=0.5,
        ),
        lambda: assess_benchmark_alpha(
            strategy_returns=(0.01, 0.02),
            benchmark_returns=(0.01, 0.02, 0.03),
            maximum_abs_alpha_for_beta_only=0.0001,
            minimum_abs_beta_for_beta_only=0.8,
        ),
    ),
)
def test_malformed_adversarial_evidence_fails_closed(invalid_check: Callable[[], GateResult]) -> None:
    with pytest.raises(ValueError):
        invalid_check()

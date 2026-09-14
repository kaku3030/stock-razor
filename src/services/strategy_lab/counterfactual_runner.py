"""Deterministic execution shell for a frozen counterfactual plan."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Mapping

from .rule_validation_contract import CounterfactualPlan, CounterfactualSpec


@dataclass(frozen=True)
class CounterfactualMeasurement:
    variant_id: str
    metrics: Mapping[str, float]

    def __post_init__(self) -> None:
        if not isinstance(self.variant_id, str) or not self.variant_id.strip():
            raise ValueError("variant_id must be non-empty")
        if not isinstance(self.metrics, Mapping) or not self.metrics:
            raise ValueError("metrics must be a non-empty mapping")
        normalized = {}
        for name, value in self.metrics.items():
            if not isinstance(name, str) or not name.strip() or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("metrics must have non-empty names and finite numeric values")
            normalized[name] = float(value)
        object.__setattr__(self, "metrics", dict(sorted(normalized.items())))


@dataclass(frozen=True)
class CounterfactualRunReport:
    plan_fingerprint: str
    measurements: tuple[CounterfactualMeasurement, ...]


def run_counterfactual_plan(plan: CounterfactualPlan, evaluator: Callable[[CounterfactualSpec], Mapping[str, float]]) -> CounterfactualRunReport:
    """Run every frozen variant once in canonical plan order."""
    if not isinstance(plan, CounterfactualPlan) or not callable(evaluator):
        raise ValueError("plan must be CounterfactualPlan and evaluator must be callable")
    measurements = tuple(CounterfactualMeasurement(item.variant_id, evaluator(item)) for item in plan.variants)
    return CounterfactualRunReport(plan.fingerprint, measurements)

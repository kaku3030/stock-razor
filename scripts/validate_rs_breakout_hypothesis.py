#!/usr/bin/env python3
"""Validate the provisional RS Breakout research hypothesis contract.

This is a contract/schema gate only. It does not register an experiment,
consume a holdout, or authorize production use.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_COUNTERFACTUALS = {
    "WITH_RULE",
    "WITHOUT_RULE",
    "SHUFFLED_PLACEBO",
    "DELAYED_RULE",
    "REGIME_CONDITIONED",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.config.read_text(encoding="utf-8"))
    errors: list[str] = []

    if payload.get("schema") != "radar-rs-breakout-hypothesis-v0.1":
        errors.append("unexpected schema")
    if payload.get("rule_id") != "oliver-kell-rs-breakout":
        errors.append("unexpected rule_id")
    if payload.get("status") != "RESEARCH_ONLY":
        errors.append("status must remain RESEARCH_ONLY")
    provenance = payload.get("provenance", {})
    if provenance.get("canonical_oliver_kell_formula") != "NOT_ESTABLISHED":
        errors.append("canonical formula must remain explicitly unestablished")
    if provenance.get("production_authorized") is not False:
        errors.append("production_authorized must be false")

    parameters = payload.get("parameters", {})
    checks = {
        "breakout_window_bars": lambda value: isinstance(value, int) and value >= 2,
        "volume_multiple": lambda value: isinstance(value, (int, float)) and value > 0,
        "relative_strength_percentile": lambda value: isinstance(value, (int, float)) and 0 < value <= 100,
        "holding_period_bars": lambda value: isinstance(value, int) and value >= 1,
    }
    for name, valid in checks.items():
        if name not in parameters or not valid(parameters[name]):
            errors.append(f"invalid parameter: {name}")

    if set(payload.get("required_counterfactuals", [])) != REQUIRED_COUNTERFACTUALS:
        errors.append("counterfactual set is incomplete or changed")
    holdout = payload.get("holdout_policy", {})
    if holdout.get("never_seen_holdout") != "PROTECTED" or holdout.get("consumes_holdout") is not False:
        errors.append("holdout policy must remain protected and non-consuming")

    result = {"status": "VALID" if not errors else "INVALID", "rule_id": payload.get("rule_id"), "errors": errors}
    print(json.dumps(result, sort_keys=True))
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())

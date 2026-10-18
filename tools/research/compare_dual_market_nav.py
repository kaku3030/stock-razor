"""Compare independent V1.3 NAV metrics with legacy V1.0/V1.1 metrics."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def _legacy(path: Path, names: set[str]) -> pd.DataFrame:
    data = pd.read_csv(path)
    return data[(data["scope"] == "MODERN_COMMON_2019_05_08_2026_10_16")
                & (data["cost_scenario"] == "5bp_fee_5bp_slippage")
                & data["strategy"].isin(names)].copy()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nav-reconciliation", type=Path, required=True)
    parser.add_argument("--v10-metrics", type=Path, required=True)
    parser.add_argument("--v11-metrics", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    nav = pd.read_csv(args.nav_reconciliation)
    nav = nav[nav["cost_scenario"] == "5bp_fee_5bp_slippage"].copy()
    nav["legacy_strategy"] = nav["strategy"].replace({
        "V1.0_STATE_SWITCH": "STATE_SWITCH_HYSTERESIS",
        "V10_BASELINE": "V10_BASELINE",
    })
    legacy = pd.concat([
        _legacy(args.v10_metrics, {"STATE_SWITCH_HYSTERESIS"}),
        _legacy(args.v11_metrics, {"V10_BASELINE", "LAYERED_DRAWDOWN", "SLOW_REENTRY"}),
    ], ignore_index=True)
    legacy["legacy_nav"] = legacy["cumulative_return"] + 1.0
    merged = nav.merge(legacy, left_on="legacy_strategy", right_on="strategy",
                       suffixes=("_independent_nav", "_legacy"))
    result = merged[["strategy_independent_nav", "legacy_nav", "final_nav",
                     "cagr_independent_nav", "cagr_legacy", "max_drawdown_independent_nav",
                     "max_drawdown_legacy", "recovery_days_independent_nav",
                     "recovery_days_legacy", "total_turnover",
                     "monthly_turnover"]].rename(columns={
                         "final_nav": "independent_nav", "cagr_independent_nav": "independent_cagr",
                         "max_drawdown_independent_nav": "independent_mdd",
                         "recovery_days_independent_nav": "independent_recovery_days"})
    result["nav_difference"] = result["independent_nav"] - result["legacy_nav"]
    result["cagr_difference"] = result["independent_cagr"] - result["cagr_legacy"]
    result["mdd_difference"] = result["independent_mdd"] - result["max_drawdown_legacy"]
    result["recovery_days_difference"] = result["independent_recovery_days"] - result["recovery_days_legacy"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(args.output, index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()

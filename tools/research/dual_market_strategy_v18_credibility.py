"""Fail-closed credibility checks and fixed-rule forward windows for V1.8."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


STRATEGIES = ("A_STATIC", "B_DYNAMIC", "AB_BLEND")
COST = "5bp_fee_5bp_slippage"
COMMON_START = pd.Timestamp("2020-12-02")
COMMON_END = pd.Timestamp("2026-10-16")
REQUIRED = {
    "date", "strategy", "cost_scenario", "start_nav", "nav", "net_return",
    "gross_return", "transaction_cost", "turnover", "price_US.QQQ",
}
WINDOWS = (("2021_2022", 2021, 2022), ("2023_2024", 2023, 2024), ("2025_2026", 2025, 2026))


def _metrics(part: pd.DataFrame) -> dict[str, object]:
    returns = part["net_return"]
    wealth = (1.0 + returns).cumprod()
    peak = wealth.cummax()
    qqq = part["price_US.QQQ"].pct_change()
    down = qqq < 0
    return {
        "start": str(part["date"].min().date()),
        "end": str(part["date"].max().date()),
        "n_days": int(len(part)),
        "return": float(wealth.iloc[-1] - 1.0),
        "mdd": float((wealth / peak - 1.0).min()),
        "qqq_return": float((1.0 + qqq.fillna(0.0)).prod() - 1.0),
        "down_day_positive_rate": float((returns[down] > 0).mean()) if down.any() else None,
        "turnover": float(part["turnover"].sum()),
    }


def audit(input_csv: Path, output_dir: Path) -> dict[str, str]:
    frame = pd.read_csv(input_csv, parse_dates=["date"])
    missing = sorted(REQUIRED - set(frame.columns))
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    frame["date"] = frame["date"].dt.normalize()
    selected = frame[
        (frame["strategy"].isin(STRATEGIES))
        & (frame["cost_scenario"] == COST)
        & frame["date"].between(COMMON_START, COMMON_END)
    ].copy()
    if selected.empty:
        raise ValueError("no selected fixed-cost strategy rows")
    numeric = ["start_nav", "nav", "net_return", "gross_return", "transaction_cost", "turnover", "price_US.QQQ"]
    if selected[numeric].isna().any().any():
        raise ValueError("selected rows contain missing accounting, cost, or QQQ price")
    if selected.duplicated(["strategy", "date"]).any():
        raise ValueError("duplicate strategy/date rows")
    date_sets = {name: set(group["date"]) for name, group in selected.groupby("strategy")}
    if set(date_sets) != set(STRATEGIES) or len({frozenset(dates) for dates in date_sets.values()}) != 1:
        raise ValueError("strategies do not share one exact trading-date set")
    selected = selected.sort_values(["strategy", "date"])
    selected["nav_error"] = (selected["nav"] - selected["start_nav"] * (1.0 + selected["net_return"])).abs()
    selected["weight_error"] = (selected["target_weight_sum"] - 1.0).abs() if "target_weight_sum" in selected else 0.0
    selected["cost_error"] = (
        selected["gross_return"] - selected["net_return"]
        - selected["transaction_cost"] / selected["start_nav"]
    ).abs()
    checks = {
        "missing_selected_values": "PASS",
        "duplicate_strategy_date": "PASS",
        "exact_shared_date_set": "PASS",
        "nav_conservation": "PASS" if float(selected["nav_error"].max()) <= 1e-12 else "FAIL",
        "return_cost_reconciliation": "PASS" if float(selected["cost_error"].max()) <= 1e-12 else "FAIL",
        "provider_finality": "UNKNOWN",
        "qfq_total_return_semantics": "UNKNOWN",
        "independent_exchange_calendar": "UNKNOWN",
        "state_lag_semantics": "UNKNOWN",
        "true_future_oos": "NOT_VERIFIED",
    }
    rows: list[dict[str, object]] = []
    for name, start_year, end_year in WINDOWS:
        window = selected[selected["date"].dt.year.between(start_year, end_year)]
        for strategy in STRATEGIES:
            part = window[window["strategy"] == strategy].sort_values("date")
            if len(part) < 2:
                rows.append({"window": name, "strategy": strategy, "status": "NOT_TESTABLE"})
                continue
            rows.append({"window": name, "strategy": strategy, "status": "MEASURABLE", "parameter_selection": "LOCKED_BEFORE_WINDOW", "oos_class": "HISTORICAL_FORWARD_ONLY_NOT_TRUE_OOS", **_metrics(part)})
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v18"
    paths = {
        "checks": output_dir / f"{prefix}_credibility_checks.json",
        "forward": output_dir / f"{prefix}_fixed_forward.csv",
        "report": output_dir / f"{prefix}_credibility_report.md",
    }
    paths["forward"].write_text(pd.DataFrame(rows).to_csv(index=False), encoding="utf-8")
    checks_payload = {
        "input_sha256": hashlib.sha256(input_csv.read_bytes()).hexdigest(),
        "input": str(input_csv),
        "window": [str(COMMON_START.date()), str(COMMON_END.date())],
        "excluded_pre_common_rows": int(((frame["strategy"].isin(STRATEGIES)) & (frame["cost_scenario"] == COST) & (frame["date"] < COMMON_START)).sum()),
        "cost_scenario": COST,
        "strategies": list(STRATEGIES),
        "checks": checks,
        "max_nav_error": float(selected["nav_error"].max()),
        "max_cost_reconciliation_error": float(selected["cost_error"].max()),
        "rows": int(len(selected)),
        "research_only": True,
        "radar_admission": "BLOCKED",
        "paper_auto_ready": "NO",
        "trade_execution": "NO",
    }
    paths["checks"].write_text(json.dumps(checks_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# STOCK RAZOR Dual-Market Strategy V1.8 credibility acceptance",
        "",
        f"Input SHA-256: `{checks_payload['input_sha256']}`",
        f"Fixed sample: `{checks_payload['window'][0]}—{checks_payload['window'][1]}`, cost `{COST}`.",
        "",
        "## Deterministic checks",
        *[f"- `{key}`: `{value}`" for key, value in checks.items()],
        "",
        "## Forward windows",
        "The windows use parameters already fixed before each window and do not select or retune on the window. They are historical forward-only slices from the same previously observed dataset, so they are `HISTORICAL_FORWARD_ONLY_NOT_TRUE_OOS`, not independent future OOS.",
        *[f"- `{row['window']}` / `{row['strategy']}`: `{row['status']}`" + (f", return `{row['return']:.2%}`, MDD `{row['mdd']:.2%}`, QQQ return `{row['qqq_return']:.2%}`" if row['status'] == 'MEASURABLE' else "") for row in rows],
        "",
        "Independent provider finality, QFQ dividend/total-return semantics, exchange-calendar independence, and state-lag semantics remain UNKNOWN. Missing evidence is not promoted.",
        "",
        "`RESEARCH_ONLY`; `RADAR_ADMISSION=BLOCKED`; `PAPER_AUTO_READY=NO`; `TRADE_EXECUTION=NO`.",
    ]
    paths["report"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.input_csv, args.output_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

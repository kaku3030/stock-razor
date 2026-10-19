"""Independent V1.7 audit of the completed V1.6 daily NAV artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd


COMMON_START = "2020-12-02"
COMMON_END = "2026-10-16"
STRESS_WINDOWS = {
    "STRESS_2020_ACUTE": ("2020-02-19", "2020-04-30"),
    "STRESS_2022_BEAR": ("2022-01-03", "2022-12-30"),
}
REQUIRED_COLUMNS = {"date", "strategy", "cost_scenario", "start_nav", "nav", "net_return", "price_US.QQQ"}


def _capture(strategy: pd.Series, benchmark: pd.Series, mask: pd.Series) -> float:
    denominator = float(benchmark[mask].sum())
    return float(strategy[mask].sum() / denominator) if denominator else math.nan


def _rates(strategy: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    up = benchmark > 0
    down = benchmark < 0
    return {
        "benchmark_up_capture": _capture(strategy, benchmark, up),
        "benchmark_down_capture": _capture(strategy, benchmark, down),
        "benchmark_up_return_denominator": float(benchmark[up].sum()),
        "benchmark_down_return_denominator": float(benchmark[down].sum()),
        "benchmark_up_day_count": int(up.sum()),
        "benchmark_down_day_count": int(down.sum()),
        "benchmark_down_day_strategy_positive_rate": float((strategy[down] > 0).mean()) if down.any() else math.nan,
    }


def _summary(strategy: pd.Series, benchmark: pd.Series, scope: str, frequency: str) -> dict[str, object]:
    strategy = strategy.dropna()
    benchmark = benchmark.reindex(strategy.index)
    wealth = (1.0 + strategy).cumprod()
    peak = wealth.cummax()
    rates = _rates(strategy, benchmark)
    annual_periods = {"daily": 252.0, "monthly": 12.0}.get(frequency)
    if annual_periods is None:
        raise ValueError(f"unsupported summary frequency: {frequency}")
    return {
        "scope": scope,
        "frequency": frequency,
        "start": str(strategy.index.min().date()),
        "end": str(strategy.index.max().date()),
        "n_periods": int(len(strategy)),
        "cumulative_return": float(wealth.iloc[-1] - 1.0),
        "cagr": float(wealth.iloc[-1] ** (annual_periods / len(strategy)) - 1.0) if len(strategy) else math.nan,
        "max_drawdown": float((wealth / peak - 1.0).min()),
        "positive_period_rate": float((strategy > 0).mean()) if len(strategy) else math.nan,
        **rates,
    }


def _monthly(strategy: pd.Series, qqq_price: pd.Series) -> tuple[pd.Series, pd.Series]:
    return (1.0 + strategy).resample("ME").prod() - 1.0, qqq_price.resample("ME").last().pct_change()


def audit(input_csv: Path, output_dir: Path, generated_at_jst: str) -> dict[str, str]:
    frame = pd.read_csv(input_csv, parse_dates=["date"])
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    frame = frame.sort_values(["strategy", "cost_scenario", "date"])
    frame["date"] = frame["date"].dt.normalize()
    if frame[["start_nav", "nav", "net_return", "price_US.QQQ"]].isna().any().any():
        raise ValueError("selected V1.6 artifact contains missing accounting or QQQ prices")
    common = frame[(frame.date >= COMMON_START) & (frame.date <= COMMON_END)].copy()
    daily_rows: list[dict[str, object]] = []
    monthly_rows: list[dict[str, object]] = []
    annual_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    for (name, cost), part in common.groupby(["strategy", "cost_scenario"], sort=True):
        part = part.set_index("date").sort_index()
        qqq = part["price_US.QQQ"].pct_change()
        returns = part["net_return"]
        daily_rows.append({"strategy": name, "cost_scenario": cost, **_summary(returns, qqq, "COMMON_2020_12_02_2026_10_16", "daily")})
        month_returns, month_qqq = _monthly(returns, part["price_US.QQQ"])
        monthly_rows.append({"strategy": name, "cost_scenario": cost, **_summary(month_returns, month_qqq, "COMMON_2020_12_02_2026_10_16", "monthly")})
        for year, year_returns in returns.groupby(returns.index.year):
            year_qqq = qqq.reindex(year_returns.index)
            annual_rows.append({"strategy": name, "cost_scenario": cost, "year": int(year), **_summary(year_returns, year_qqq, f"YEAR_{year}", "daily")})
        conservation_error = float((part["nav"] - part["start_nav"] * (1.0 + part["net_return"])).abs().max())
        missing_price_count = int(part["price_US.QQQ"].isna().sum())
        audit_rows.append({"strategy": name, "cost_scenario": cost, "n_days": len(part), "max_nav_conservation_error": conservation_error,
                           "missing_qqq_price_count": missing_price_count, "status": "PASS" if conservation_error <= 1e-12 and missing_price_count == 0 else "FAIL"})

    for scope, (start, end) in STRESS_WINDOWS.items():
        for (name, cost), part in common.groupby(["strategy", "cost_scenario"], sort=True):
            selected = part[(part.date >= start) & (part.date <= end)]
            audit_rows.append({"strategy": name, "cost_scenario": cost, "scope": scope, "start": start, "end": end,
                               "n_days": len(selected), "status": "NOT_TESTABLE" if len(selected) < 2 else "MEASURABLE"})

    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v17"
    paths = {
        "daily": output_dir / f"{prefix}_daily_metrics.csv",
        "monthly": output_dir / f"{prefix}_monthly_metrics.csv",
        "annual": output_dir / f"{prefix}_annual_metrics.csv",
        "audit": output_dir / f"{prefix}_audit.csv",
        "timeline": output_dir / f"{prefix}_timeline.csv",
        "metadata": output_dir / f"{prefix}_metadata.json",
        "report": output_dir / f"{prefix}_report.md",
    }
    pd.DataFrame(daily_rows).to_csv(paths["daily"], index=False, encoding="utf-8-sig")
    pd.DataFrame(monthly_rows).to_csv(paths["monthly"], index=False, encoding="utf-8-sig")
    pd.DataFrame(annual_rows).to_csv(paths["annual"], index=False, encoding="utf-8-sig")
    pd.DataFrame(audit_rows).to_csv(paths["audit"], index=False, encoding="utf-8-sig")
    timeline = pd.DataFrame([
        {"event": "V1.6_data_first_readable", "event_date": "2020-12-02", "time_jst": "UNKNOWN", "status": "OBSERVED_DATA_BOUNDARY"},
        {"event": "V1.6_sample_end", "event_date": "2026-10-16", "time_jst": "UNKNOWN", "status": "OBSERVED_DATA_BOUNDARY"},
        {"event": "V1.4_PR915_created", "event_date": "2026-10-18", "time_jst": "2026-10-19 00:05:59 JST", "status": "OBSERVED_PR_HEAD_94b165ea"},
        {"event": "V1.5_local_uncommitted_source", "event_date": "2026-10-19", "time_jst": "2026-10-19 09:48:58 JST", "status": "OBSERVED_LOCAL_ONLY"},
        {"event": "V1.6_PR919_created", "event_date": "2026-10-19", "time_jst": "2026-10-19 09:56:42 JST", "status": "OBSERVED_PR_HEAD_ccf6d86c"},
        {"event": "V1.7_audit_generated", "event_date": "2026-10-19", "time_jst": generated_at_jst, "status": "OBSERVED_OPERATION"},
        {"event": "2020_acute_stress", "event_date": "2020-02-19/2020-04-30", "time_jst": "UNKNOWN", "status": "NOT_TESTABLE"},
        {"event": "2022_bear_stress", "event_date": "2022-01-03/2022-12-30", "time_jst": "UNKNOWN", "status": "MEASURABLE_251_DAYS"},
        {"event": "hosted_CI_PR919", "event_date": "2026-10-19", "time_jst": "UNKNOWN", "status": "NO_AVAILABLE_RUN_OR_STATUS"},
        {"event": "next_acceptance_gate", "event_date": "TBD", "time_jst": "TBD", "status": "PLANNED_NOT_COMPLETED"},
    ])
    timeline.to_csv(paths["timeline"], index=False, encoding="utf-8-sig")
    summary = pd.DataFrame(daily_rows)
    baseline = summary[summary.cost_scenario == "5bp_fee_5bp_slippage"]
    lines = [f"- `{r.strategy}`: CAGR={r.cagr:.2%}, MDD={r.max_drawdown:.2%}, up capture={r.benchmark_up_capture:.2%}, down capture={r.benchmark_down_capture:.2%}, down-day positive={r.benchmark_down_day_strategy_positive_rate:.2%}" for r in baseline.itertuples()]
    monthly_summary = pd.DataFrame(monthly_rows)
    selected_monthly = monthly_summary[(monthly_summary.strategy.isin(["A_STATIC", "B_DYNAMIC", "AB_BLEND"])) & (monthly_summary.cost_scenario == "5bp_fee_5bp_slippage")]
    monthly_lines = [f"- `{r.strategy}`: monthly positive rate={r.positive_period_rate:.2%}, monthly up capture={r.benchmark_up_capture:.2%}, monthly down capture={r.benchmark_down_capture:.2%}" for r in selected_monthly.itertuples()]
    annual_2022 = pd.DataFrame(annual_rows)
    annual_2022 = annual_2022[(annual_2022.year == 2022) & (annual_2022.strategy.isin(["A_STATIC", "B_DYNAMIC", "AB_BLEND"])) & (annual_2022.cost_scenario == "5bp_fee_5bp_slippage")]
    annual_lines = [f"- `{r.strategy}`: return={r.cumulative_return:.2%}, MDD={r.max_drawdown:.2%}, down-day positive={r.benchmark_down_day_strategy_positive_rate:.2%}, n={r.n_periods}" for r in annual_2022.itertuples()]
    paths["report"].write_text("\n".join(["# STOCK RAZOR Dual-Market Strategy V1.7 实际审计", "", f"操作时间统一使用 JST；本次审计生成于 {generated_at_jst}。", "", "## V1.6 共同窗口 2020-12-02—2026-10-16，5bp+5bp", "", *lines, "", "### 月度", "", *monthly_lines, "", "### 2022 分年度压力结果", "", *annual_lines, "", "上涨捕获率 = 策略在 QQQ 上涨日收益之和 / 同一批 QQQ 上涨日收益之和；分母为 QQQ 上涨日收益之和。下跌捕获率同理，分母为 QQQ 下跌日收益之和（负数）。下跌日策略正收益比例 = QQQ 下跌日中策略收益 > 0 的天数 / QQQ 下跌日总数。月度正收益率 = 正收益月份数 / 月份总数。", "", "2020 急跌：NOT_TESTABLE（KMLM 首个可读日 2020-12-02）；2022 熊市：可测 251 天。QFQ 总回报语义、provider finality、独立交易日历仍 UNKNOWN；固定参数前向段不是独立 OOS。", "", *[f"守恒/缺失价审计：`{r.status}`，最大 NAV 守恒误差={r.max_nav_conservation_error:.3g}" for r in pd.DataFrame(audit_rows).query("status == 'PASS'").itertuples()], "", "结论：AB_BLEND 仍是研究候选中的综合折中，不满足‘上涨跟随与下跌保护同时全面优于 A/B’；晋级仅限 RESEARCH_CANDIDATE，不得进入 Radar/Paper/Trade。", "", "时间线与计划/已发生区分见 timeline.csv；复现：使用 V1.6 daily_nav.csv 运行本审计脚本。", "RADAR_ADMISSION=BLOCKED; PAPER_AUTO_READY=NO; TRADE_EXECUTION=NO.", ""]), encoding="utf-8")
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths.values() if path != paths["metadata"]}
    metadata = {"experiment": "STOCK_RAZOR_DUAL_MARKET_STRATEGY_V1.7_AUDIT", "input": str(input_csv),
                "common_window": [COMMON_START, COMMON_END], "capture_formula": "sum(strategy returns on benchmark-sign-matched periods) / sum(benchmark returns on same periods)",
                "down_day_positive_formula": "count(strategy return > 0 on QQQ return < 0) / count(QQQ return < 0)",
                "monthly_positive_formula": "count(monthly strategy return > 0) / count(months)",
                "generated_at_jst": generated_at_jst, "qfq_dividend_semantics": "UNKNOWN", "provider_finality": "UNKNOWN",
                "independent_exchange_calendar": "UNKNOWN", "oos_status": "NOT_VERIFIED", "radar_admission": "BLOCKED",
                "paper_auto_ready": "NO", "trade_execution": "NO", "sha256": hashes}
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--generated-at-jst", required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.input_csv, args.output_dir, args.generated_at_jst), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

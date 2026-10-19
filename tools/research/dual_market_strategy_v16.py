"""Research-only V1.6 A/B complementarity experiment.

All rules are frozen before replay. Portfolios are replayed through the V1.4
explicit shares/cash accounting engine; no NAV curves are blended after the
fact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

from tools.research.dual_market_accounting import replay_portfolio, target_schedule
from tools.research.dual_market_strategy_v08 import COSTS, DEFAULT_END, fetch_history, metric_row, price_frame
from tools.research.dual_market_strategy_v10 import BASELINE_WEIGHTS as V10_BASELINES, WEIGHTS as V10_WEIGHTS, state_path


COMMON_START = "2020-12-02"
COMMON_END = DEFAULT_END
SHORT_BOND = "US.SGOV"
SHORT_BOND_FALLBACK = "US.SHV"
STRESS_WINDOWS = {
    "STRESS_2020_ACUTE": ("2020-02-19", "2020-04-30"),
    "STRESS_2022_BEAR": ("2022-01-03", "2022-12-30"),
}
FORWARD_WINDOWS = {
    "ROLLING_FORWARD_2023": ("2023-01-03", "2023-12-29"),
    "ROLLING_FORWARD_2024": ("2024-01-02", "2024-12-31"),
    "ROLLING_FORWARD_2025": ("2025-01-02", "2025-12-31"),
    "ROLLING_FORWARD_2026": ("2026-01-02", "2026-10-16"),
}
A_WEIGHTS = {"US.QQQ": .40, "US.SCHD": .20, "US.KMLM": .20, "US.GLD": .20}
QQQ_ONLY = {"US.QQQ": 1.0}
B_DYNAMIC_WEIGHTS = {
    "RISK_ON": {"US.QQQ": .40, "US.DBMF": .25, "US.BTAL": .15, "US.GLD": .20},
    "NEUTRAL": {"US.QQQ": .25, "US.DBMF": .20, "US.BTAL": .15, "US.GLD": .20, "US.SGOV": .20},
    "DEFENSIVE": {"US.QQQ": .10, "US.DBMF": .20, "US.BTAL": .15, "US.GLD": .20, "US.SGOV": .35},
}


def _rename_short_bond(weights: dict[str, float], short_bond: str) -> dict[str, float]:
    return {short_bond if symbol == SHORT_BOND else symbol: weight for symbol, weight in weights.items()}


def _blend(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    symbols = sorted(set(left) | set(right))
    return {symbol: (left.get(symbol, 0.0) + right.get(symbol, 0.0)) / 2.0 for symbol in symbols}


def _metric(name: str, ledger: pd.DataFrame, qqq: pd.Series, scope: str, cost_label: str) -> dict:
    returns = ledger["net_return"].dropna()
    row = metric_row(name, returns, ledger["turnover"], qqq.reindex(returns.index), scope, cost_label)
    down = qqq.reindex(returns.index) < 0
    row["qqq_down_day_strategy_positive_rate"] = float((returns[down] > 0).mean()) if down.any() else math.nan
    row["turnover_sum"] = float(ledger["turnover"].reindex(returns.index).sum())
    row["frequency"] = "daily"
    return row


def _metrics(name: str, ledger: pd.DataFrame, qqq: pd.Series, cost_label: str) -> list[dict]:
    rows: list[dict] = []
    common = ledger.loc[COMMON_START:]
    for scope, part in (("FULL", ledger), ("COMMON_2020_12_02_2026_10_16", common)):
        if len(part) < 2:
            continue
        rows.append(_metric(name, part, qqq, scope, cost_label))
        monthly = part["net_return"].resample("ME").apply(lambda s: (1.0 + s).prod() - 1.0)
        monthly_ledger = part.copy()
        monthly_ledger["net_return"] = monthly
        monthly_ledger["turnover"] = part["turnover"].resample("ME").sum()
        monthly_row = _metric(name, monthly_ledger.dropna(subset=["net_return"]), qqq.resample("ME").apply(lambda s: (1.0 + s).prod() - 1.0), scope, cost_label)
        monthly_row["frequency"] = "monthly"
        rows.append(monthly_row)
        for year, year_part in part.groupby(part.index.year):
            rows.append(_metric(name, year_part, qqq, f"{scope}_YEAR_{year}", cost_label))
    for scope, (start, end) in STRESS_WINDOWS.items():
        part = ledger.loc[start:end]
        if len(part) < 2:
            rows.append({"strategy": name, "scope": scope, "cost_scenario": cost_label, "status": "NOT_TESTABLE", "n_days": len(part)})
        else:
            rows.append(_metric(name, part, qqq, scope, cost_label))
    for scope, (start, end) in FORWARD_WINDOWS.items():
        part = ledger.loc[start:end]
        if len(part) >= 2:
            rows.append(_metric(name, part, qqq, scope, cost_label) | {"validation": "FIXED_PARAMETER_FORWARD_NOT_INDEPENDENT_OOS"})
        else:
            rows.append({"strategy": name, "scope": scope, "cost_scenario": cost_label, "status": "NOT_TESTABLE", "n_days": len(part), "validation": "FIXED_PARAMETER_FORWARD_NOT_INDEPENDENT_OOS"})
    return rows


def evaluate(raw: dict[str, pd.DataFrame], output_dir: Path, end: str, errors: dict[str, str]) -> dict[str, str]:
    if "US.QQQ" not in raw:
        raise RuntimeError(f"required QQQ unavailable: {errors.get('US.QQQ')}")
    short_bond = SHORT_BOND if SHORT_BOND in raw else SHORT_BOND_FALLBACK if SHORT_BOND_FALLBACK in raw else None
    if short_bond is None:
        raise RuntimeError("required short-bond proxy unavailable")
    a = _rename_short_bond(A_WEIGHTS, short_bond)
    b_by_state = {state: _rename_short_bond(weights, short_bond) for state, weights in B_DYNAMIC_WEIGHTS.items()}
    b_symbols = sorted({symbol for weights in b_by_state.values() for symbol in weights})
    b_prices = price_frame(raw, b_symbols)
    ab_prices = price_frame(raw, sorted(set(b_symbols) | set(a)))
    b_signal_prices = price_frame(raw, sorted(set(b_symbols) | {"US.QQQ", "US.SCHD"}))
    b_states = state_path(b_signal_prices).reindex(b_prices.index, method="ffill").fillna("NEUTRAL")
    b_state_weights = b_by_state
    ab_blend_weights = {state: _blend(a, weights) for state, weights in b_by_state.items()}
    ab_switch_weights = {"RISK_ON": a, "NEUTRAL": ab_blend_weights["NEUTRAL"], "DEFENSIVE": b_by_state["DEFENSIVE"]}
    v10_weights = {state: _rename_short_bond(weights, short_bond) for state, weights in V10_WEIGHTS.items()}
    v10_prices = price_frame(raw, sorted({symbol for weights in v10_weights.values() for symbol in weights}))
    v10_states = state_path(v10_prices)
    qqq = raw["US.QQQ"].set_index("date")["close"].pct_change()
    all_symbols = sorted(set(a) | set(b_symbols) | set(v10_prices.columns) | {"US.QQQ"})
    coverage = []
    for symbol in all_symbols:
        frame = raw.get(symbol)
        coverage.append({"symbol": symbol, "status": "OK" if frame is not None else "ERROR_OR_EMPTY", "first_readable_date": str(frame.date.min().date()) if frame is not None else None, "last_readable_date": str(frame.date.max().date()) if frame is not None else None, "rows": int(len(frame)) if frame is not None else 0, "error": errors.get(symbol)})
    ledgers: list[pd.DataFrame] = []
    metrics: list[dict] = []
    for fee, slippage, label in COSTS:
        candidates = {
            "A_STATIC": (a, None, None), "B_DYNAMIC": ({}, b_states, b_state_weights),
            "AB_BLEND": ({}, b_states, ab_blend_weights), "AB_SWITCH": ({}, b_states, ab_switch_weights),
            "V1.0_STATE_SWITCH": ({}, v10_states, v10_weights), "QQQ_ONLY": (QQQ_ONLY, None, None),
        }
        for name, (weights, states, state_weights) in candidates.items():
            if states is None:
                prices = price_frame(raw, list(weights))
                targets, rebalance = target_schedule(prices, weights)
            else:
                prices = ab_prices if name in {"AB_BLEND", "AB_SWITCH"} else b_prices if name == "B_DYNAMIC" else v10_prices
                aligned_states = states.reindex(prices.index, method="ffill")
                targets, rebalance = target_schedule(prices, {}, state=aligned_states, state_weights=state_weights)
            ledger = replay_portfolio(prices, targets, rebalance, fee, slippage)
            ledger["strategy"], ledger["cost_scenario"] = name, label
            ledgers.append(ledger.reset_index())
            metrics.extend(_metrics(name, ledger, qqq, label))
    prefix = "stock_razor_dual_market_strategy_v16"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {key: output_dir / f"{prefix}_{suffix}" for key, suffix in {"ledger": "daily_nav.csv", "metrics": "metrics.csv", "coverage": "coverage_matrix.csv", "difference": "difference.csv", "metadata": "metadata.json", "report": "report.md"}.items()}
    pd.concat(ledgers, ignore_index=True).to_csv(paths["ledger"], index=False, encoding="utf-8-sig")
    metrics_frame = pd.DataFrame(metrics)
    metrics_frame.to_csv(paths["metrics"], index=False, encoding="utf-8-sig")
    pd.DataFrame(coverage).to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    common = metrics_frame[(metrics_frame["scope"] == "COMMON_2020_12_02_2026_10_16") & (metrics_frame["frequency"] == "daily")]
    common = common[common["cost_scenario"].isin(["5bp_fee_5bp_slippage", "10bp_fee_10bp_slippage"])]
    fields = ["cagr", "max_drawdown", "recovery_days", "qqq_up_day_follow_rate", "qqq_down_day_strategy_positive_rate", "sharpe", "calmar", "turnover_sum"]
    differences = []
    for cost, group in common.groupby("cost_scenario"):
        indexed = group.set_index("strategy")
        for strategy in ("AB_BLEND", "AB_SWITCH"):
            for baseline in ("A_STATIC", "B_DYNAMIC"):
                if strategy in indexed.index and baseline in indexed.index:
                    differences.append({"cost_scenario": cost, "strategy": strategy, "baseline": baseline, **{f"delta_{field}": float(indexed.loc[strategy, field] - indexed.loc[baseline, field]) for field in fields}})
    pd.DataFrame(differences).to_csv(paths["difference"], index=False, encoding="utf-8-sig")
    metadata = {"experiment": "STOCK_RAZOR_DUAL_MARKET_STRATEGY_V1.6", "source": "local OpenD only", "endpoint": "127.0.0.1:11111", "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ", "end": end}, "rules_frozen": True, "a_weights": A_WEIGHTS, "b_dynamic_state_weights": B_DYNAMIC_WEIGHTS, "ab_switch": "RISK_ON=A; NEUTRAL=50/50 A+B; DEFENSIVE=B", "execution": "closed daily signal, next readable row, explicit shares/cash, drift between rebalances", "common_window": [COMMON_START, COMMON_END], "stress_windows": STRESS_WINDOWS, "forward_windows": FORWARD_WINDOWS, "qfq_dividend_semantics": "UNKNOWN", "provider_finality": "UNKNOWN", "independent_exchange_calendar": "UNKNOWN", "oos_status": "NOT_VERIFIED; fixed-parameter forward segments are not independent OOS", "radar_admission": "BLOCKED", "paper_auto_ready": "NO", "trade_execution": "NO"}
    metadata["sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (paths["ledger"], paths["metrics"], paths["coverage"], paths["difference"])}
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    key = metrics_frame[(metrics_frame["scope"] == "COMMON_2020_12_02_2026_10_16") & (metrics_frame["cost_scenario"] == COSTS[0][2]) & (metrics_frame.get("frequency", "daily") == "daily")]
    lines = [f"- `{row.strategy}`: CAGR={row.cagr:.2%}, MDD={row.max_drawdown:.2%}, recovery={row.recovery_days}, QQQ up={row.qqq_up_day_follow_rate:.2%}, QQQ down positive={row.qqq_down_day_strategy_positive_rate:.2%}, turnover={row.turnover_sum:.4f}" for row in key.itertuples()]
    paths["report"].write_text("\n".join(["# STOCK RAZOR Dual-Market Strategy V1.6", "", "规则在回放前冻结；所有组合通过 V1.4 显式 shares/cash/NAV 引擎计算。", "", "## 共同窗口 2020-12-02—2026-10-16，5bp+5bp", "", *lines, "", "A/B 混合和切换是目标权重调度，不是事后 NAV 拼接。滚动前向段使用固定参数，但不是独立 OOS。", "2020 急跌中缺失上市历史的组合标记 NOT_TESTABLE；QFQ、provider finality、独立交易日历保持 UNKNOWN。", "RADAR_ADMISSION=BLOCKED; PAPER_AUTO_READY=NO; TRADE_EXECUTION=NO." ]) + "\n", encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    from futu import OpenQuoteContext
    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    raw, errors = {}, {}
    try:
        symbols = sorted(set(A_WEIGHTS) | {symbol for weights in B_DYNAMIC_WEIGHTS.values() for symbol in weights} | {symbol for weights in V10_WEIGHTS.values() for symbol in weights} | {"US.SHV"})
        for symbol in symbols:
            frame, status = fetch_history(ctx, symbol, args.end)
            if frame is None:
                errors[symbol] = status
            else:
                raw[symbol] = frame
    finally:
        ctx.close()
    print(json.dumps(evaluate(raw, args.output_dir, args.end, errors), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

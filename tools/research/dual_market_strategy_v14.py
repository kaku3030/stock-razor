"""Research-only V1.4 unified accounting replay and cross-strategy audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from tools.research.dual_market_accounting import replay_portfolio, target_schedule
from tools.research.dual_market_strategy_v08 import (
    ALL_SYMBOLS as V08_SYMBOLS,
    COSTS,
    DEFAULT_END,
    FORMAL_START,
    OFFICIAL_INCEPTION_DATES,
    OFFICIAL_SOURCES,
    OFFICIAL_TRADING_DATES,
    STRESS_WINDOWS,
    fetch_history,
    metric_row,
    monthly_rebalanced_returns,
    price_frame,
    recovery_days,
)
from tools.research.dual_market_strategy_v10 import (
    ALL_SYMBOLS as V10_SYMBOLS,
    BASELINE_WEIGHTS as V10_BASELINES,
    WEIGHTS as V10_STATE_WEIGHTS,
    state_path as v10_state_path,
    state_returns as v10_legacy_state_returns,
)


STATIC_STRATEGIES = {
    "QQQ_ONLY": {"US.QQQ": 1.0},
    "QQQ_SCHD_GLD_50_30_20": {"US.QQQ": .50, "US.SCHD": .30, "US.GLD": .20},
    "B_UPSIDE_HEDGE": V10_BASELINES["B_UPSIDE_HEDGE"],
    "C_BALANCED_COMPOUND": {"US.QQQ": .50, "US.DBMF": .20, "US.BTAL": .10, "US.IEF": .20},
    "F_BALANCED_DEFENSIVE": V10_BASELINES["F_BALANCED_DEFENSIVE"],
}
ROLLING_SEGMENTS = (
    ("2012_01_03_2016_12_30", "2012-01-03", "2016-12-30"),
    ("2015_01_02_2019_12_31", "2015-01-02", "2019-12-31"),
    ("2018_01_02_2022_12_30", "2018-01-02", "2022-12-30"),
    ("2021_01_04_2026_10_16", "2021-01-04", "2026-10-16"),
)
ALL_SYMBOLS = sorted(set(V08_SYMBOLS) | set(V10_SYMBOLS) | {
    symbol for weights in STATIC_STRATEGIES.values() for symbol in weights
})


def _scopes(name: str, ledger: pd.DataFrame, qqq: pd.Series, label: str) -> list[dict]:
    returns = ledger["net_return"]
    turnover = ledger["turnover"]
    full = returns.loc[FORMAL_START:]
    if len(full) < 2:
        return []
    rows = [metric_row(name, full, turnover, qqq.reindex(full.index), "FULL_CHRONOLOGICAL_REPLAY", label)]
    modern = full.loc["2019-05-08":]
    if len(modern) > 1:
        rows.append(metric_row(name, modern, turnover, qqq.reindex(modern.index),
                               "MODERN_COMMON_2019_05_08_2026_10_16", label))
    for year, part in full.groupby(full.index.year):
        rows.append(metric_row(name, part, turnover, qqq.reindex(part.index), f"YEAR_{year}", label))
    for year in STRESS_WINDOWS:
        part = full[full.index.year == year]
        if len(part) > 1:
            rows.append(metric_row(name, part, turnover, qqq.reindex(part.index), f"STRESS_{year}", label))
    return rows


def _metric_summary(metrics: pd.DataFrame, strategy: str, label: str, scope: str) -> dict:
    row = metrics[(metrics.strategy == strategy) & (metrics.cost_scenario == label) & (metrics.scope == scope)].iloc[0]
    return {key: float(row[key]) if key not in {"strategy", "cost_scenario", "scope"} else row[key]
            for key in ("strategy", "cost_scenario", "scope", "cumulative_return", "cagr",
                        "max_drawdown", "recovery_days", "monthly_turnover", "worst_day", "worst_month")}


def evaluate(raw: dict[str, pd.DataFrame], output_dir: Path, end: str,
             errors: dict[str, str]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    qqq = raw["US.QQQ"].set_index("date")["close"].pct_change()
    metrics_rows: list[dict] = []
    ledgers: list[pd.DataFrame] = []
    differences: list[dict] = []
    coverage = []

    for symbol in ALL_SYMBOLS:
        frame = raw.get(symbol)
        coverage.append({
            "symbol": symbol, "status": "OK" if frame is not None else "ERROR_OR_EMPTY",
            "first_readable_date": str(frame.date.min().date()) if frame is not None else None,
            "last_readable_date": str(frame.date.max().date()) if frame is not None else None,
            "rows": int(len(frame)) if frame is not None else 0, "error": errors.get(symbol),
            "official_inception_date": OFFICIAL_INCEPTION_DATES.get(symbol),
            "official_trading_date": OFFICIAL_TRADING_DATES.get(symbol),
        })

    for fee, slippage, label in COSTS:
        if not set(V10_SYMBOLS) - set(raw):
            prices = price_frame(raw, V10_SYMBOLS)
            states = v10_state_path(prices)
            targets, rebalance = target_schedule(prices, {}, state=states, state_weights=V10_STATE_WEIGHTS)
            ledger = replay_portfolio(prices, targets, rebalance, fee, slippage)
            strategy = "V1.0_STATE_SWITCH"
            ledger["strategy"], ledger["cost_scenario"] = strategy, label
            ledgers.append(ledger.reset_index())
            metrics_rows.extend(_scopes(strategy, ledger, qqq, label))
            old_returns, old_turnover, _ = v10_legacy_state_returns(prices, fee, slippage)
            old = old_returns.loc[FORMAL_START:]
            new = ledger["net_return"].loc[FORMAL_START:]
            differences.append({"strategy": strategy, "cost_scenario": label, "old_accounting": "implicit_daily_rebalance",
                                "new_accounting": "state_change_only_drifted_holdings", "old_final_nav": float((1 + old).prod()),
                                "new_final_nav": float(ledger.loc[FORMAL_START:, "nav"].iloc[-1]),
                                "old_cagr": float((1 + old).prod() ** (252 / len(old)) - 1),
                                "new_cagr": float((1 + new).prod() ** (252 / len(new)) - 1),
                                "old_mdd": float((1 + old).cumprod().div((1 + old).cumprod().cummax()).sub(1).min()),
                                "new_mdd": float((1 + new).cumprod().div((1 + new).cumprod().cummax()).sub(1).min()),
                                "old_turnover": float(old_turnover.loc[FORMAL_START:].sum()),
                                "new_turnover": float(ledger.loc[FORMAL_START:, "turnover"].sum())})

        for strategy, weights in STATIC_STRATEGIES.items():
            if set(weights) - set(raw):
                continue
            prices = price_frame(raw, list(weights))
            targets, rebalance = target_schedule(prices, weights)
            ledger = replay_portfolio(prices, targets, rebalance, fee, slippage)
            ledger["strategy"], ledger["cost_scenario"] = strategy, label
            ledgers.append(ledger.reset_index())
            metrics_rows.extend(_scopes(strategy, ledger, qqq, label))
            old_returns, old_turnover = monthly_rebalanced_returns(prices, weights, fee, slippage)
            old = old_returns.loc[FORMAL_START:]
            new = ledger["net_return"].loc[FORMAL_START:]
            differences.append({"strategy": strategy, "cost_scenario": label, "old_accounting": "monthly_rebalance",
                                "new_accounting": "initial_only_drifted_holdings", "old_final_nav": float((1 + old).prod()),
                                "new_final_nav": float(ledger.loc[FORMAL_START:, "nav"].iloc[-1]),
                                "old_cagr": float((1 + old).prod() ** (252 / len(old)) - 1),
                                "new_cagr": float((1 + new).prod() ** (252 / len(new)) - 1),
                                "old_mdd": float((1 + old).cumprod().div((1 + old).cumprod().cummax()).sub(1).min()),
                                "new_mdd": float((1 + new).cumprod().div((1 + new).cumprod().cummax()).sub(1).min()),
                                "old_turnover": float(old_turnover.loc[FORMAL_START:].sum()),
                                "new_turnover": float(ledger.loc[FORMAL_START:, "turnover"].sum())})

    for frame in ledgers:
        strategy = str(frame["strategy"].iloc[0])
        label = str(frame["cost_scenario"].iloc[0])
        ledger = frame.set_index("date")
        for segment, start, segment_end in ROLLING_SEGMENTS:
            part = ledger.loc[start:segment_end]
            if len(part) > 1:
                metrics_rows.append(metric_row(
                    strategy, part["net_return"], part["turnover"],
                    qqq.reindex(part.index), f"ROLLING_{segment}", label
                ))

    prefix = "stock_razor_dual_market_strategy_v14"
    paths = {
        "ledger": output_dir / f"{prefix}_daily_nav_ledger.csv",
        "metrics": output_dir / f"{prefix}_metrics.csv",
        "differences": output_dir / f"{prefix}_legacy_difference.csv",
        "coverage": output_dir / f"{prefix}_coverage_matrix.csv",
        "rolling": output_dir / f"{prefix}_rolling_segments.csv",
        "metadata": output_dir / f"{prefix}_metadata.json",
        "report": output_dir / f"{prefix}_report.md",
    }
    pd.concat(ledgers, ignore_index=True).to_csv(paths["ledger"], index=False, encoding="utf-8-sig")
    metrics = pd.DataFrame(metrics_rows)
    metrics.to_csv(paths["metrics"], index=False, encoding="utf-8-sig")
    pd.DataFrame(differences).to_csv(paths["differences"], index=False, encoding="utf-8-sig")
    pd.DataFrame(coverage).to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    rolling = metrics[metrics["scope"].astype(str).str.startswith("ROLLING_")]
    rolling.to_csv(paths["rolling"], index=False, encoding="utf-8-sig")
    metadata = {
        "source": "local OpenD only", "endpoint": "127.0.0.1:11111",
        "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ", "end": end},
        "accounting": "explicit shares and cash; target weights only on first/state-change rows; no implicit daily rebalance",
        "dividends": "QFQ close series only; dividend cash-flow semantics UNKNOWN",
        "signal_timing": "closed_prior_rows_only_next_day_effective",
        "first_readable_dates": "strategy-specific inner join; no pre-listing backfill",
        "rolling_segments": ROLLING_SEGMENTS,
        "provider_finality": "UNKNOWN", "timezone_exchange_calendar": "UNKNOWN",
        "qfq_dividend_semantics": "UNKNOWN", "oos_status": "NOT_VERIFIED",
        "radar_admission": "BLOCKED", "paper_auto_ready": "NO", "trade_execution": "NO",
    }
    metadata["sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in paths.values()
                            if path != paths["metadata"] and path.exists()}
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    modern = metrics[(metrics.scope == "MODERN_COMMON_2019_05_08_2026_10_16") &
                     (metrics.cost_scenario == COSTS[0][2])]
    lines = [f"- `{r.strategy}`: CAGR={r.cagr:.2%}, MDD={r.max_drawdown:.2%}, recovery={r.recovery_days}, "
             f"turnover={r.monthly_turnover:.4f}, worst_day={r.worst_day:.2%}, worst_month={r.worst_month:.2%}"
             for r in modern.itertuples()]
    paths["report"].write_text("\n".join([
        "# STOCK RAZOR Dual-Market Strategy V1.4 统一会计重算", "",
        f"共同回放窗口：2019-05-08—{end}；真实来源为本机 OpenD K_DAY/RTH/QFQ。",
        "统一引擎显式记录 shares/cash/price/target weight/actual drift/turnover/cost/NAV；静态组合只首日建仓，状态策略只在状态变化时调仓。", "",
        "## 共同窗口 5bp+5bp", "", *lines, "",
        "旧版差异、逐日 NAV、年度/2020/2022 压力行、固定滚动分段和覆盖矩阵见 CSV。",
        "QFQ 股息/总回报语义、provider finality、独立交易日历仍 UNKNOWN；OOS=NOT_VERIFIED。",
        "RADAR_ADMISSION=BLOCKED；PAPER_AUTO_READY=NO；TRADE_EXECUTION=NO。", "",
    ]) + "\n", encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def main(output_dir: Path, end: str = DEFAULT_END) -> None:
    from futu import OpenQuoteContext
    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    raw, errors = {}, {}
    try:
        for symbol in ALL_SYMBOLS:
            frame, status = fetch_history(ctx, symbol, end)
            if frame is None:
                errors[symbol] = status
            else:
                raw[symbol] = frame
    finally:
        ctx.close()
    if "US.QQQ" not in raw:
        raise RuntimeError(f"required QQQ unavailable: {errors.get('US.QQQ')}")
    print(json.dumps(evaluate(raw, output_dir, end, errors), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    main(args.output_dir, args.end)

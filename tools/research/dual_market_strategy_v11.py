"""Research-only V1.1 state-switch candidates and causal attribution.

All candidate rules are declared in this file before replay. Signals use only
closed rows before the evaluated day and affect the next available day.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v08 import (
    COSTS, DEFAULT_END, FORMAL_START, OFFICIAL_INCEPTION_DATES,
    OFFICIAL_SOURCES, OFFICIAL_TRADING_DATES, STRESS_WINDOWS,
    fetch_history, metric_row, monthly_rebalanced_returns, price_frame,
)
from tools.research.dual_market_strategy_v10 import (
    ALL_SYMBOLS as V10_SYMBOLS, BASELINE_WEIGHTS, NEUTRAL, RISK_ON,
    DEFENSIVE, _conditions,
)


# Frozen finite candidates. They differ by one interpretable mechanism each;
# this is not an optimizer and no threshold is selected from replay results.
CANDIDATES = {
    "V10_BASELINE": {"entry_days": 2, "neutral_drawdown": -0.08,
                     "defensive_drawdown": -0.15, "risk_on_days": 10,
                     "exit_days": 5, "layered_neutral": False},
    "LAYERED_DRAWDOWN": {"entry_days": 2, "neutral_drawdown": -0.10,
                         "defensive_drawdown": -0.15, "risk_on_days": 10,
                         "exit_days": 5, "layered_neutral": True},
    "SLOW_REENTRY": {"entry_days": 2, "neutral_drawdown": -0.08,
                     "defensive_drawdown": -0.15, "risk_on_days": 20,
                     "exit_days": 10, "layered_neutral": False},
}

WEIGHTS = {"RISK_ON": RISK_ON, "NEUTRAL": NEUTRAL, "DEFENSIVE": DEFENSIVE}
ALL_SYMBOLS = sorted(set(V10_SYMBOLS))


def _conditions_v11(prior: pd.DataFrame, cfg: dict) -> tuple[bool, bool, bool]:
    risk_on, defensive = _conditions(prior)
    if len(prior) < 126:
        return False, False, False
    qqq = prior["US.QQQ"]
    drawdown = float(qqq.iloc[-1] / qqq.tail(126).max() - 1.0)
    layered_neutral = drawdown <= cfg["neutral_drawdown"]
    layered_defensive = drawdown <= cfg["defensive_drawdown"]
    return risk_on, defensive or layered_defensive, layered_neutral


def state_path(prices: pd.DataFrame, cfg: dict) -> pd.Series:
    state = "NEUTRAL"
    defensive_count = neutral_count = risk_on_count = repair_count = 0
    states = []
    for i, _date in enumerate(prices.index):
        prior = prices.iloc[:i]
        risk_on, defensive, neutral = _conditions_v11(prior, cfg)
        defensive_count = defensive_count + 1 if defensive else 0
        neutral_count = neutral_count + 1 if neutral else 0
        risk_on_count = risk_on_count + 1 if risk_on else 0
        repair_count = repair_count + 1 if risk_on else 0
        if state != "DEFENSIVE" and defensive_count >= cfg["entry_days"]:
            state = "DEFENSIVE"
            repair_count = risk_on_count = 0
        elif (cfg["layered_neutral"] and state == "RISK_ON"
              and neutral_count >= cfg["entry_days"]):
            state = "NEUTRAL"
            risk_on_count = 0
        elif state == "DEFENSIVE" and repair_count >= cfg["exit_days"]:
            state = "NEUTRAL"
            risk_on_count = 0
        elif state == "NEUTRAL" and neutral_count >= cfg["entry_days"]:
            state = "NEUTRAL"
        elif state == "NEUTRAL" and risk_on_count >= cfg["risk_on_days"]:
            state = "RISK_ON"
        states.append(state)
    return pd.Series(states, index=prices.index, name="state")


def state_returns(prices: pd.DataFrame, cfg: dict, fee_bps: float,
                  slippage_bps: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    states = state_path(prices, cfg)
    daily = prices.pct_change().fillna(0.0)
    current = pd.Series(0.0, index=prices.columns)
    cost_rate = (fee_bps + slippage_bps) / 10000.0
    values, turnovers = [], []
    for date, row in daily.iterrows():
        target = pd.Series(WEIGHTS[states.loc[date]], dtype=float).reindex(
            prices.columns, fill_value=0.0)
        turnover = float((target - current).abs().sum())
        values.append(float((target * row).sum()) - turnover * cost_rate)
        turnovers.append(turnover)
        current = target
    return (pd.Series(values, index=prices.index),
            pd.Series(turnovers, index=prices.index), states)


def _episodes(states: pd.Series, turnovers: pd.Series,
              returns: pd.Series) -> pd.DataFrame:
    changed = states.ne(states.shift())
    starts = list(states.index[changed])
    rows = []
    for i, start in enumerate(starts):
        end = starts[i + 1] - pd.Timedelta(days=1) if i + 1 < len(starts) else states.index[-1]
        part = returns.loc[start: end]
        rows.append({"start": str(start.date()), "end": str(end.date()),
                     "state": states.loc[start], "days": int(len(part)),
                     "return": float((1 + part).prod() - 1),
                     "entry_turnover": float(turnovers.loc[start])})
    return pd.DataFrame(rows)


def _scope_rows(name: str, returns: pd.Series, turnover: pd.Series,
                qqq: pd.Series, label: str) -> list[dict]:
    full = returns.loc[FORMAL_START:]
    if len(full) < 2:
        return []
    rows = [metric_row(name, full, turnover, qqq.reindex(full.index),
                       "FULL_CHRONOLOGICAL_REPLAY", label)]
    modern = full.loc["2019-05-08":]
    if len(modern) > 1:
        rows.append(metric_row(name, modern, turnover, qqq.reindex(modern.index),
                               "MODERN_COMMON_2019_05_08_2026_10_16", label))
    for year, part in full.groupby(full.index.year):
        rows.append(metric_row(name, part, turnover, qqq.reindex(part.index),
                               f"YEAR_{year}", label))
    for year in STRESS_WINDOWS:
        part = full[full.index.year == year]
        if len(part) > 1:
            rows.append(metric_row(name, part, turnover, qqq.reindex(part.index),
                                   f"FULL_CHRONOLOGICAL_REPLAY_STRESS_{year}", label))
    return rows


def evaluate_v11(raw: dict[str, pd.DataFrame], output_dir: Path, end: str,
                 errors: dict[str, str]) -> dict[str, str]:
    missing = set(ALL_SYMBOLS) - set(raw)
    if missing:
        raise RuntimeError(f"required V1.1 symbols unavailable: {sorted(missing)}")
    prices = price_frame(raw, ALL_SYMBOLS)
    qqq = prices["US.QQQ"].pct_change()
    rows, state_rows, episode_rows = [], [], []
    for fee, slip, label in COSTS:
        for name, cfg in CANDIDATES.items():
            result, turnover, states = state_returns(prices, cfg, fee, slip)
            rows.extend(_scope_rows(name, result, turnover, qqq, label))
            state_rows.append(pd.DataFrame({"date": states.index, "state": states.values,
                                            "turnover": turnover.values,
                                            "candidate": name, "cost_scenario": label}))
            episodes = _episodes(states, turnover, result)
            episodes["candidate"], episodes["cost_scenario"] = name, label
            episode_rows.append(episodes)
        for name, weights in BASELINE_WEIGHTS.items():
            p = price_frame(raw, list(weights))
            result, turnover = monthly_rebalanced_returns(p, weights, fee, slip)
            rows.extend(_scope_rows(name, result, turnover,
                                    raw["US.QQQ"].set_index("date")["close"].pct_change(), label))
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v11_2026-10-18"
    paths = {key: output_dir / f"{prefix}_{suffix}" for key, suffix in {
        "metrics": "metrics.csv", "states": "states.csv", "episodes": "episodes.csv",
        "coverage": "coverage.csv", "metadata": "metadata.json", "report": "report.md"}.items()}
    metrics = pd.DataFrame(rows)
    metrics.to_csv(paths["metrics"], index=False, encoding="utf-8-sig")
    pd.concat(state_rows, ignore_index=True).to_csv(paths["states"], index=False, encoding="utf-8-sig")
    pd.concat(episode_rows, ignore_index=True).to_csv(paths["episodes"], index=False, encoding="utf-8-sig")
    coverage = pd.DataFrame([{
        "symbol": symbol, "status": "OK" if symbol in raw else "ERROR_OR_EMPTY",
        "first_readable_date": str(raw[symbol].date.min().date()) if symbol in raw else None,
        "last_readable_date": str(raw[symbol].date.max().date()) if symbol in raw else None,
        "rows": int(len(raw[symbol])) if symbol in raw else 0, "error": errors.get(symbol),
        "official_inception_date": OFFICIAL_INCEPTION_DATES.get(symbol),
        "official_trading_date": OFFICIAL_TRADING_DATES.get(symbol),
    } for symbol in ALL_SYMBOLS])
    coverage.to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    metadata = {"source": "local OpenD only", "endpoint": "127.0.0.1:11111",
        "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ", "end": end},
        "rules_frozen_before_replay": True, "candidates": CANDIDATES,
        "weights": WEIGHTS, "signal_timing": "closed_prior_rows_only_next_day_effective",
        "asset_first_readable_day_constraint": True, "official_sources": OFFICIAL_SOURCES,
        "provider_finality": "UNKNOWN", "timezone_exchange_calendar": "UNKNOWN",
        "qfq_dividend_semantics": "UNKNOWN",
        "return_type": "PRICE_RETURN_SENSITIVITY_NOT_PROVEN_TOTAL_RETURN",
        "oos_status": "NOT_VERIFIED", "trade_execution": "NO", "radar_admission": "BLOCKED",
        "paper_auto_ready": "NO"}
    metadata["sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in (paths["metrics"], paths["states"], paths["episodes"], paths["coverage"])}
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    modern = metrics[(metrics.scope == "MODERN_COMMON_2019_05_08_2026_10_16") &
                     (metrics.cost_scenario == COSTS[0][2])]
    lines = [f"- `{r.strategy}`: CAGR={r.cagr:.2%}, MDD={r.max_drawdown:.2%}, "
             f"recovery={r.recovery_days}, Calmar={r.calmar:.2f}, worst_day={r.worst_day:.2%}, "
             f"worst_month={r.worst_month:.2%}, turnover={r.monthly_turnover:.2f}"
             for r in modern.itertuples()]
    paths["report"].write_text("\n".join([
        "# STOCK RAZOR Dual-Market Strategy V1.1", "",
        f"真实回放区间：2019-05-08—{end}；仅使用本机 OpenD K_DAY/RTH/QFQ。",
        "候选规则在回放前固定；信号只读取已闭合历史行，并于下一可读交易日生效。", "",
        "## 共同窗口（5bp+5bp）", "", *lines, "",
        "## 规则与解释", "",
        "- V10_BASELINE：V1.0 三态基线。",
        "- LAYERED_DRAWDOWN：只改变中性层回撤触发为 -10%，保留防御 -15%，测试分层降风险。",
        "- SLOW_REENTRY：只延长防御退出/风险重入确认，测试重入延迟对反复切换的影响。",
        "- 2020/2022 状态切换、episode 收益、进入换手和所有年度/压力指标见 CSV。", "",
        "## 限制", "",
        "缺失资产不替代、不回填；QFQ 股息/总回报语义 UNKNOWN。OOS=NOT_VERIFIED；provider finality 与独立交易日历 UNKNOWN。",
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
    print(json.dumps(evaluate_v11(raw, output_dir, end, errors), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    main(args.output_dir, args.end)

"""Research-only three-state dual-market strategy replay.

The state machine is frozen before replay. Signals use only closed rows before
the evaluated day and become effective on the next trading day. Results remain
price-return sensitivity because OpenD QFQ total-return semantics are UNKNOWN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research.dual_market_strategy_v08 import (
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
)
from tools.research.dual_market_strategy_v09 import (
    TREND_OFF,
    TREND_ON,
    dynamic_returns,
    trend_signal,
)


STATES = ("RISK_ON", "NEUTRAL", "DEFENSIVE")
LOOKBACK = 126
VOL_LOOKBACK = 20
VOL_NEUTRAL = 0.30
VOL_DEFENSIVE = 0.35
DRAWDOWN_NEUTRAL = -0.08
DRAWDOWN_DEFENSIVE = -0.15
ENTER_CONFIRMATION = 2
DEFENSIVE_EXIT_CONFIRMATION = 5
RISK_ON_CONFIRMATION = 10

RISK_ON = {"US.QQQ": .60, "US.SCHD": .30, "US.GLD": .10}
NEUTRAL = {"US.QQQ": .40, "US.SCHD": .20, "US.GLD": .10, "US.SHV": .30}
DEFENSIVE = {"US.QQQ": .20, "US.SCHD": .10, "US.GLD": .10, "US.SHV": .60}
WEIGHTS = {"RISK_ON": RISK_ON, "NEUTRAL": NEUTRAL, "DEFENSIVE": DEFENSIVE}
BASELINE_WEIGHTS = {
    "QQQ_ONLY": {"US.QQQ": 1.0},
    "GROWTH_CORE_60_30_10": {"US.QQQ": .60, "US.SCHD": .30, "US.GLD": .10},
    "B_UPSIDE_HEDGE": {"US.QQQ": .35, "US.DBMF": .25, "US.BTAL": .20, "US.SHV": .20},
    "F_BALANCED_DEFENSIVE": {"US.QQQ": .45, "US.DBMF": .15, "US.BTAL": .15, "US.IEF": .25},
}
ALL_SYMBOLS = sorted({symbol for weights in {**WEIGHTS, **BASELINE_WEIGHTS}.values() for symbol in weights})


def _trend_and_risk(prior: pd.DataFrame) -> tuple[bool, bool, bool, float]:
    if len(prior) < LOOKBACK:
        return False, False, False, 0.0
    qqq = prior["US.QQQ"]
    schd = prior["US.SCHD"]
    qqq_trend = float(qqq.iloc[-1]) > float(qqq.tail(LOOKBACK).mean())
    schd_trend = float(schd.iloc[-1]) > float(schd.tail(LOOKBACK).mean())
    core = prior[["US.QQQ", "US.SCHD"]].pct_change().dropna().dot([.70, .30])
    annualized_vol = float(core.tail(VOL_LOOKBACK).std(ddof=1) * np.sqrt(252))
    qqq_drawdown = float(qqq.iloc[-1] / qqq.tail(LOOKBACK).max() - 1.0)
    return qqq_trend, schd_trend, annualized_vol, qqq_drawdown


def _conditions(prior: pd.DataFrame) -> tuple[bool, bool]:
    qqq_trend, schd_trend, annualized_vol, qqq_drawdown = _trend_and_risk(prior)
    if len(prior) < LOOKBACK:
        return False, False
    risk_on = qqq_trend and schd_trend and annualized_vol <= VOL_NEUTRAL and qqq_drawdown > DRAWDOWN_NEUTRAL
    defensive = (not qqq_trend and annualized_vol >= VOL_DEFENSIVE) or qqq_drawdown <= DRAWDOWN_DEFENSIVE
    return risk_on, defensive


def state_path(prices: pd.DataFrame) -> pd.Series:
    """Return the state effective on each day using only earlier closes."""
    state = "NEUTRAL"
    defensive_count = 0
    repair_count = 0
    risk_on_count = 0
    states = []
    for i, _date in enumerate(prices.index):
        prior = prices.iloc[:i]
        risk_on, defensive = _conditions(prior)
        if defensive:
            defensive_count += 1
        else:
            defensive_count = 0
        if risk_on:
            repair_count += 1
            risk_on_count += 1
        else:
            repair_count = 0
            risk_on_count = 0
        if state != "DEFENSIVE" and defensive_count >= ENTER_CONFIRMATION:
            state = "DEFENSIVE"
            repair_count = 0
            risk_on_count = 0
        elif state == "DEFENSIVE" and repair_count >= DEFENSIVE_EXIT_CONFIRMATION:
            state = "NEUTRAL"
            risk_on_count = 0
        elif state == "NEUTRAL" and risk_on_count_count(risk_on_count):
            state = "RISK_ON"
        states.append(state)
    return pd.Series(states, index=prices.index, name="state")


def risk_on_count_count(count: int) -> bool:
    return count >= RISK_ON_CONFIRMATION


def state_returns(prices: pd.DataFrame, fee_bps: float, slippage_bps: float) -> tuple[pd.Series, pd.Series, pd.Series]:
    states = state_path(prices)
    returns = prices.pct_change().fillna(0.0)
    current = pd.Series(0.0, index=prices.columns)
    values, turnovers = [], []
    cost_rate = (fee_bps + slippage_bps) / 10000.0
    for date, daily in returns.iterrows():
        target = pd.Series(WEIGHTS[states.loc[date]], dtype=float).reindex(prices.columns, fill_value=0.0)
        turnover = float((target - current).abs().sum())
        values.append(float((target * daily).sum()) - turnover * cost_rate)
        turnovers.append(turnover)
        current = target
    return pd.Series(values, index=prices.index), pd.Series(turnovers, index=prices.index), states


def _scope_rows(name: str, returns: pd.Series, turnover: pd.Series, qqq: pd.Series, label: str) -> list[dict]:
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
            rows.append(metric_row(name, part, turnover, qqq.reindex(part.index),
                                   f"FULL_CHRONOLOGICAL_REPLAY_STRESS_{year}", label))
    return rows


def evaluate_v10(raw: dict[str, pd.DataFrame], output_dir: Path, end: str,
                 errors: dict[str, str]) -> dict[str, str]:
    if set(ALL_SYMBOLS) - set(raw):
        raise RuntimeError(f"required V1.0 symbols unavailable: {sorted(set(ALL_SYMBOLS) - set(raw))}")
    prices = price_frame(raw, ALL_SYMBOLS)
    qqq = prices["US.QQQ"].pct_change()
    rows = []
    state_rows = []
    for fee, slip, label in COSTS:
        result, turnover, states = state_returns(prices, fee, slip)
        rows.extend(_scope_rows("STATE_SWITCH_HYSTERESIS", result, turnover, qqq, label))
        state_rows.append(pd.DataFrame({"date": states.index, "state": states.values,
                                        "turnover": turnover.values, "cost_scenario": label}))
        for name, weights in BASELINE_WEIGHTS.items():
            baseline_prices = price_frame(raw, list(weights))
            baseline, baseline_turnover = monthly_rebalanced_returns(baseline_prices, weights, fee, slip)
            rows.extend(_scope_rows(name, baseline, baseline_turnover,
                                    raw["US.QQQ"].set_index("date")["close"].pct_change(), label))
        trend_prices = price_frame(raw, sorted(set(TREND_ON) | set(TREND_OFF)))
        trend_result, trend_turnover, _trend_states = dynamic_returns(
            trend_prices, TREND_ON, TREND_OFF, trend_signal, fee, slip)
        rows.extend(_scope_rows("GROWTH_TREND_RISK_BUDGET", trend_result, trend_turnover,
                                raw["US.QQQ"].set_index("date")["close"].pct_change(), label))
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v10_2026-10-18"
    paths = {key: output_dir / f"{prefix}_{suffix}" for key, suffix in {
        "metrics": "metrics.csv", "states": "states.csv", "coverage": "coverage.csv",
        "metadata": "metadata.json", "report": "report.md"}.items()}
    metrics = pd.DataFrame(rows)
    metrics.to_csv(paths["metrics"], index=False, encoding="utf-8-sig")
    pd.concat(state_rows, ignore_index=True).to_csv(paths["states"], index=False, encoding="utf-8-sig")
    coverage = pd.DataFrame([{
        "symbol": symbol, "status": "OK" if symbol in raw else "ERROR_OR_EMPTY",
        "first_readable_date": str(raw[symbol].date.min().date()) if symbol in raw else None,
        "last_readable_date": str(raw[symbol].date.max().date()) if symbol in raw else None,
        "rows": int(len(raw[symbol])) if symbol in raw else 0, "error": errors.get(symbol),
        "official_inception_date": OFFICIAL_INCEPTION_DATES.get(symbol),
        "official_trading_date": OFFICIAL_TRADING_DATES.get(symbol),
    } for symbol in ALL_SYMBOLS])
    coverage.to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    metadata = {
        "source": "local OpenD only", "endpoint": "127.0.0.1:11111",
        "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ", "end": end},
        "formal_start": FORMAL_START, "rules_frozen_before_replay": True,
        "states": STATES, "weights": WEIGHTS, "lookback_days": LOOKBACK,
        "comparison_baselines": BASELINE_WEIGHTS,
        "comparison_dynamic_baseline": "GROWTH_TREND_RISK_BUDGET from V0.9 frozen 126-day trend rule",
        "volatility_lookback_days": VOL_LOOKBACK, "vol_neutral": VOL_NEUTRAL,
        "vol_defensive": VOL_DEFENSIVE, "drawdown_neutral": DRAWDOWN_NEUTRAL,
        "drawdown_defensive": DRAWDOWN_DEFENSIVE, "enter_confirmation_days": ENTER_CONFIRMATION,
        "defensive_exit_confirmation_days": DEFENSIVE_EXIT_CONFIRMATION,
        "risk_on_confirmation_days": RISK_ON_CONFIRMATION,
        "signal_timing": "closed_prior_rows_only_next_day_effective",
        "insufficient_history_state": "NEUTRAL",
        "breadth": "NOT_USED_NO_VERIFIED_REAL_READABLE_COMPONENT_UNIVERSE",
        "official_sources": OFFICIAL_SOURCES, "provider_finality": "UNKNOWN",
        "qfq_dividend_semantics": "UNKNOWN", "return_type": "PRICE_RETURN_SENSITIVITY_NOT_PROVEN_TOTAL_RETURN",
        "oos_status": "NOT_VERIFIED", "trade_execution": "NO", "radar_admission": "BLOCKED",
        "candidate_selection": "PREDECLARED_NO_OPTIMIZATION",
    }
    metadata["sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in (paths["metrics"], paths["states"], paths["coverage"])}
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    modern = metrics[(metrics.scope == "MODERN_COMMON_2019_05_08_2026_10_16") &
                     (metrics.cost_scenario == COSTS[0][2])]
    lines = [f"- `{row.strategy}`: CAGR={row.cagr:.2%}, MDD={row.max_drawdown:.2%}, recovery={row.recovery_days}, "
             f"Calmar={row.calmar:.2f}, Sharpe={row.sharpe:.2f}, worst_day={row.worst_day:.2%}, "
             f"worst_month={row.worst_month:.2%}, turnover={row.monthly_turnover:.2f}, "
             f"QQQ_up={row.qqq_up_day_follow_rate:.2%}, QQQ_down_still_up={row.qqq_down_day_countertrend_up_rate:.2%}"
             for row in modern.itertuples()]
    long_controls = metrics[(metrics.scope == "FULL_CHRONOLOGICAL_REPLAY") &
                            (metrics.cost_scenario == COSTS[0][2]) &
                            (metrics.strategy == "QQQ_ONLY")]
    long_lines = [f"- `{row.strategy}`: {row.start}—{row.end}, CAGR={row.cagr:.2%}, MDD={row.max_drawdown:.2%}, "
                  f"recovery={row.recovery_days}, Calmar={row.calmar:.2f}"
                  for row in long_controls.itertuples()]
    paths["report"].write_text("\n".join([
        "# STOCK RAZOR Dual-Market Strategy V1.0", "",
        f"正式回放区间：{FORMAL_START}—{end}；仅使用本机 OpenD K_DAY/RTH/QFQ。",
        "三态风险状态与迟滞规则在回放前固定，信号只读取已收盘的历史行，并于下一交易日生效；不足 126 日历史时保持 neutral。", "",
        "## 2019-05-08 起共同窗口（5bp+5bp）", "", *lines, "",
        "比较项包含纯增长核心、B、F 和 V0.9 趋势风险预算；每个比较项使用自身真实共同可读窗口，缺失资产不静默替代。", "",
        "## 2006-10-04 起真实可读长期控制（5bp+5bp）", "", *long_lines,
        "SCHD 组合从其首个可读日开始；DBMF/BTAL 组合不能冒充 2006—2018 长期验证。", "",
        "## 固定规则", "",
        f"- risk-on：QQQ 与 SCHD 均高于 {LOOKBACK} 日均线、核心年化波动不超过 {VOL_NEUTRAL:.0%}、QQQ 回撤高于 {DRAWDOWN_NEUTRAL:.0%}。",
        f"- defensive：QQQ 低于均线且核心年化波动至少 {VOL_DEFENSIVE:.0%}，或 QQQ 回撤达到 {DRAWDOWN_DEFENSIVE:.0%}；连续 {ENTER_CONFIRMATION} 日确认后进入。",
        f"- neutral：其余状态；defensive 修复连续 {DEFENSIVE_EXIT_CONFIRMATION} 日后先回 neutral，neutral 回 risk-on 需连续 {RISK_ON_CONFIRMATION} 日确认。",
        "- 未使用市场广度：当前没有经过验证的真实可读成分股广度数据，不能用代理数据冒充。", "",
        "## 限制", "",
        "SCHD/DBMF 的上市前历史不回填；本 V1.0 共同窗口从 SCHD 可读日起计算。QFQ 股息/总回报语义仍 UNKNOWN，因此指标是价格收益敏感性，不是已证明的总回报。",
        "2025—2026 已观察，OOS=NOT_VERIFIED；provider_finality=UNKNOWN；timezone_exchange_calendar=UNKNOWN。",
        "RADAR_ADMISSION=BLOCKED；PAPER_AUTO_READY=NO；TRADE_EXECUTION=NO。详细年度、压力窗口、状态序列、成本敏感性和覆盖矩阵见 CSV/JSON。", "",
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
    print(json.dumps(evaluate_v10(raw, output_dir, end, errors), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    main(args.output_dir, args.end)

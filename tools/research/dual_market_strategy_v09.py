"""Research-only V0.9 dual-market strategy replay.

The V0.9 candidates are frozen before replay. Dynamic signals use only data
available before the evaluated trading day and take effect on the next day.
OpenD QFQ dividend semantics remain UNKNOWN, so results are price-return
sensitivity rather than proven total-return performance.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

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
)


VOL_THRESHOLD = 0.30
VOL_LOOKBACK = 20
TREND_LOOKBACK = 126
FUTU_HISTORY_DOC = "https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html"
STATIC_CANDIDATES = {
    "QQQ_ONLY": {"US.QQQ": 1.0},
    "GROWTH_CORE_60_30_10": {"US.QQQ": .60, "US.SCHD": .30, "US.GLD": .10},
    "GROWTH_DEFENSE_DBFM_BTAL": {"US.QQQ": .50, "US.SCHD": .25, "US.DBMF": .15, "US.BTAL": .10},
    "B_UPSIDE_HEDGE": {"US.QQQ": .35, "US.DBMF": .25, "US.BTAL": .20, "US.SHV": .20},
    "F_BALANCED_DEFENSIVE": {"US.QQQ": .45, "US.DBMF": .15, "US.BTAL": .15, "US.IEF": .25},
    "QQQ_SCHD_GLD_50_30_20": {"US.QQQ": .50, "US.SCHD": .30, "US.GLD": .20},
}
VOL_ON = {"US.QQQ": .60, "US.SCHD": .30, "US.GLD": .10}
VOL_OFF = {"US.QQQ": .30, "US.SCHD": .15, "US.GLD": .10, "US.SHV": .45}
TREND_ON = VOL_ON
TREND_OFF = {"US.QQQ": .30, "US.SCHD": .15, "US.GLD": .10, "US.SHV": .45}
ALL_SYMBOLS = sorted({symbol for weights in STATIC_CANDIDATES.values() for symbol in weights} | {
    *V08_SYMBOLS, "US.SHV", "US.IEF"
})


def _target_for_signal(target: dict[str, float], available: pd.Index) -> pd.Series:
    missing = set(target) - set(available)
    if missing:
        raise ValueError(f"missing required symbols: {sorted(missing)}")
    return pd.Series(target, dtype=float).reindex(available, fill_value=0.0)


def dynamic_returns(
    prices: pd.DataFrame,
    on_weights: dict[str, float],
    off_weights: dict[str, float],
    signal,
    fee_bps: float,
    slippage_bps: float,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Apply a pre-close signal at the next day's open proxy.

    Prices are daily close-to-close returns. At date i, signal receives only
    prices strictly before i; the selected target is charged before i's return.
    """
    returns = prices.pct_change().fillna(0.0)
    current = pd.Series(0.0, index=prices.columns)
    values, turnovers, states = [], [], []
    cost_rate = (fee_bps + slippage_bps) / 10000.0
    for i, (date, daily) in enumerate(returns.iterrows()):
        prior = prices.iloc[:i]
        risk_off = bool(signal(prior))
        target = _target_for_signal(off_weights if risk_off else on_weights, prices.columns)
        turnover = float((target - current).abs().sum())
        daily_return = float((target * daily).sum()) - turnover * cost_rate
        values.append(daily_return)
        turnovers.append(turnover)
        states.append("OFF" if risk_off else "ON")
        current = target
    index = returns.index
    return pd.Series(values, index=index), pd.Series(turnovers, index=index), pd.Series(states, index=index)


def volatility_signal(prior: pd.DataFrame) -> bool:
    if len(prior) < VOL_LOOKBACK + 1:
        return False
    core = prior[["US.QQQ", "US.SCHD"]].pct_change().dropna().dot([.70, .30])
    return float(core.tail(VOL_LOOKBACK).std(ddof=1) * np.sqrt(252)) > VOL_THRESHOLD


def trend_signal(prior: pd.DataFrame) -> bool:
    if len(prior) < TREND_LOOKBACK:
        return False
    qqq = prior["US.QQQ"]
    return float(qqq.iloc[-1]) < float(qqq.iloc[-TREND_LOOKBACK:].mean())


def _scope_rows(name: str, returns: pd.Series, turnover: pd.Series, qqq: pd.Series,
                cost_label: str) -> list[dict]:
    full = returns.loc[FORMAL_START:]
    if len(full) < 2:
        return []
    rows = [metric_row(name, full, turnover, qqq.reindex(full.index), "FULL_CHRONOLOGICAL_REPLAY", cost_label)]
    modern = full.loc["2019-05-08":]
    if len(modern) > 1:
        rows.append(metric_row(name, modern, turnover, qqq.reindex(modern.index),
                               "MODERN_COMMON_2019_05_08_2026_10_16", cost_label))
    for year, part in full.groupby(full.index.year):
        rows.append(metric_row(name, part, turnover, qqq.reindex(part.index), f"YEAR_{year}", cost_label))
    for year in STRESS_WINDOWS:
        part = full[full.index.year == year]
        if len(part) > 1:
            rows.append(metric_row(name, part, turnover, qqq.reindex(part.index),
                                   f"FULL_CHRONOLOGICAL_REPLAY_STRESS_{year}", cost_label))
    return rows


def evaluate_v09(raw: dict[str, pd.DataFrame], output_dir: Path, end: str,
                 errors: dict[str, str]) -> dict[str, str]:
    coverage = []
    for symbol in ALL_SYMBOLS:
        frame = raw.get(symbol)
        coverage.append({
            "symbol": symbol, "status": "OK" if frame is not None else "ERROR_OR_EMPTY",
            "first_readable_date": str(frame.date.min().date()) if frame is not None else None,
            "last_readable_date": str(frame.date.max().date()) if frame is not None else None,
            "rows": int(len(frame)) if frame is not None else 0,
            "official_inception_date": OFFICIAL_INCEPTION_DATES.get(symbol),
            "official_trading_date": OFFICIAL_TRADING_DATES.get(symbol),
            "error": errors.get(symbol),
        })
    required = set(VOL_ON) | {"US.DBMF", "US.BTAL", "US.IEF", "US.SHV"}
    if not required.issubset(raw):
        missing = sorted(required - set(raw))
        raise RuntimeError(f"required V0.9 symbols unavailable: {missing}")
    qqq = raw["US.QQQ"].set_index("date")["close"].pct_change()
    rows = []
    for name, weights in STATIC_CANDIDATES.items():
        if not set(weights).issubset(raw):
            continue
        prices = price_frame(raw, list(weights))
        for fee, slip, label in COSTS:
            result, turnover = monthly_rebalanced_returns(prices, weights, fee, slip)
            rows.extend(_scope_rows(name, result, turnover, qqq, label))
    dynamic_prices = price_frame(raw, sorted(set(VOL_ON) | {"US.SHV"}))
    trend_prices = dynamic_prices
    for name, on, off, signal in (
        ("GROWTH_VOL_CONTROL", VOL_ON, VOL_OFF, volatility_signal),
        ("GROWTH_TREND_RISK_BUDGET", TREND_ON, TREND_OFF, trend_signal),
    ):
        for fee, slip, label in COSTS:
            result, turnover, states = dynamic_returns(dynamic_prices if name == "GROWTH_VOL_CONTROL" else trend_prices,
                                                       on, off, signal, fee, slip)
            rows.extend(_scope_rows(name, result, turnover, qqq, label))
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v09_2026-10-18"
    paths = {key: output_dir / f"{prefix}_{suffix}" for key, suffix in {
        "metrics": "metrics.csv", "coverage": "coverage.csv", "metadata": "metadata.json", "report": "report.md"}.items()}
    metrics = pd.DataFrame(rows)
    metrics.to_csv(paths["metrics"], index=False, encoding="utf-8-sig")
    pd.DataFrame(coverage).to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    metadata = {
        "source": "local OpenD only", "endpoint": "127.0.0.1:11111",
        "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ", "end": end},
        "formal_start": FORMAL_START, "rules_frozen_before_replay": True,
        "dynamic_signal_effective": "next_trading_day_close_to_close_proxy",
        "volatility_rule": {"lookback_days": VOL_LOOKBACK, "annualized_threshold": VOL_THRESHOLD,
                             "on_weights": VOL_ON, "off_weights": VOL_OFF},
        "trend_rule": {"lookback_days": TREND_LOOKBACK, "on_weights": TREND_ON, "off_weights": TREND_OFF},
        "static_candidates": STATIC_CANDIDATES, "stress_windows": STRESS_WINDOWS,
        "official_sources": {**OFFICIAL_SOURCES, "futu_history_api": FUTU_HISTORY_DOC},
        "provider_finality": "UNKNOWN",
        "qfq_dividend_semantics": "UNKNOWN", "return_type": "PRICE_RETURN_SENSITIVITY_NOT_PROVEN_TOTAL_RETURN",
        "oos_status": "NOT_VERIFIED", "trade_execution": "NO", "radar_admission": "BLOCKED",
        "candidate_selection": "PREDECLARED_NO_OPTIMIZATION",
    }
    metadata["sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in (paths["metrics"], paths["coverage"])}
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = metrics[(metrics.scope == "MODERN_COMMON_2019_05_08_2026_10_16") &
                      (metrics.cost_scenario == COSTS[0][2])]
    lines = [f"- `{r.strategy}`: CAGR={r.cagr:.2%}, MDD={r.max_drawdown:.2%}, recovery={r.recovery_days}, "
             f"Calmar={r.calmar:.2f}, Sharpe={r.sharpe:.2f}, worst_day={r.worst_day:.2%}, "
             f"worst_month={r.worst_month:.2%}, turnover={r.monthly_turnover:.2f}, "
             f"QQQ跟涨={r.qqq_up_day_follow_rate:.2%}, QQQ下跌仍涨={r.qqq_down_day_countertrend_up_rate:.2%}"
             for r in summary.itertuples()]
    coverage_lines = [f"- `{r['symbol']}`: {r['first_readable_date']}—{r['last_readable_date']} ({r['status']})"
                      for r in coverage]
    paths["report"].write_text("\n".join([
        "# STOCK RAZOR Dual-Market Strategy V0.9", "",
        f"正式区间按每个候选真实共同可读日开始，数据截至 {end}；仅使用本机 OpenD 127.0.0.1:11111 K_DAY/RTH/QFQ。",
        "候选在回放前固定，费用为 5bp+5bp 与 10bp+10bp；动态信号只读取前一日收盘，下一交易日生效。", "",
        "## 2019-05-08 起共同窗口摘要（5bp+5bp）", "", *lines, "",
        "## 候选规则", "",
        f"- 波动控制：QQQ/SCHD 70/30 核心的前 {VOL_LOOKBACK} 日年化波动超过 {VOL_THRESHOLD:.0%} 时，下一日股票敞口减半并转入 SHV。",
        f"- 趋势风险预算：前一日 QQQ 收盘低于前 {TREND_LOOKBACK} 个可读日均线时，下一日采用防御权重。",
        "- 独立防御层：QQQ/SCHD/DBMF/BTAL = 50/25/15/10；DBMF/BTAL 可读性不足时整组不计算，不回填。", "",
        "## 覆盖", "", *coverage_lines, "",
        "## 限制", "",
        "Futu 文档确认接口参数是 QFQ 调整类型，但未提供可独立核对的逐笔股息纳入/总回报定义；Schwab 官方页提供 SCHD 分配记录和含再投资的基金表现口径。两者不能证明本次 OpenD QFQ 输出等于总回报，因此仍 UNKNOWN，指标只能称价格收益敏感性。",
        "DBMF/BTAL 的首个可读日限制其长期覆盖；没有把 2008 结果移植到该组。缺失资产不静默替代。",
        "provider_finality=UNKNOWN；timezone_exchange_calendar=UNKNOWN；RADAR_ADMISSION=BLOCKED；PAPER_AUTO_READY=NO；TRADE_EXECUTION=NO。",
        "年度、2008/2020/2022 压力、最差日/月、换手、跟涨与逆势上涨率见 metrics.csv。", "",
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
    print(json.dumps(evaluate_v09(raw, output_dir, end, errors), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    main(args.output_dir, args.end)

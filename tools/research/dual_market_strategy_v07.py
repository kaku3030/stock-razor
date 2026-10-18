"""Bounded V0.7 dual-market attribution and stress research replay.

This is research-only. Rules and candidates are fixed before the OpenD replay;
signals, where applicable, use closed daily bars and execute on the next bar.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from futu import AuType, KL_FIELD, KLType, OpenQuoteContext, RET_OK, Session


def fetch_history(ctx: OpenQuoteContext, code: str, end: str) -> tuple[pd.DataFrame | None, str]:
    ret, data, desc = ctx.request_history_kline(
        code, start="1990-01-01", end=end, ktype=KLType.K_DAY,
        autype=AuType.QFQ, fields=KL_FIELD.ALL_REAL, max_count=None,
        extended_time=False, session=Session.RTH,
    )
    if ret != RET_OK or data is None or data.empty:
        return None, str(desc if ret != RET_OK else "empty")
    frame = data.copy()
    frame["date"] = pd.to_datetime(frame["time_key"], errors="coerce").dt.normalize()
    frame = frame.dropna(subset=["date", "close"]).drop_duplicates("date").sort_values("date")
    return frame.loc[frame["date"] <= pd.Timestamp(end), ["date", "close"]].reset_index(drop=True), "OK"


FORMAL_START = "2006-10-04"
DEFAULT_END = "2026-10-16"
COSTS = ((5, 5, "5bp_fee_5bp_slippage"), (10, 10, "10bp_fee_10bp_slippage"))
STRESS_YEARS = (2008, 2020, 2022)
# Frozen before replay. The variants are comparisons, not an optimizer.
CANDIDATES = {
    "B_UPSIDE_HEDGE": {"US.QQQ": .35, "US.DBMF": .25, "US.BTAL": .20, "US.SHV": .20},
    "C_BALANCED_COMPOUND": {"US.QQQ": .50, "US.DBMF": .20, "US.BTAL": .10, "US.IEF": .20},
    "D_IALT_HEDGE": {"US.QQQ": .45, "US.IALT": .20, "US.BTAL": .15, "US.IEF": .20},
    "E_IALT_DEFENSIVE": {"US.QQQ": .40, "US.IALT": .20, "US.BTAL": .15, "US.SHV": .25},
    "F_BALANCED_DEFENSIVE": {"US.QQQ": .45, "US.DBMF": .15, "US.BTAL": .15, "US.IEF": .25},
}
ALL_SYMBOLS = sorted({symbol for weights in CANDIDATES.values() for symbol in weights})


def max_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    return float((wealth / wealth.cummax() - 1.0).min())


def recovery_days(returns: pd.Series) -> float:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    peak = wealth.cummax()
    trough = (wealth / peak - 1.0).idxmin()
    recovered = wealth.loc[trough:][wealth.loc[trough:] >= peak.loc[trough]]
    if recovered.empty:
        return math.nan
    return float(wealth.index.get_loc(recovered.index[0]) - wealth.index.get_loc(trough))


def price_frame(raw: dict[str, pd.DataFrame], symbols: list[str]) -> pd.DataFrame:
    return pd.concat(
        {code: raw[code].set_index("date")["close"] for code in symbols}, axis=1, join="inner"
    ).sort_index()


def portfolio_returns(prices: pd.DataFrame, weights: dict[str, float], fee_bps: float, slippage_bps: float):
    weight_frame = pd.DataFrame(weights, index=prices.index)
    turnover = weight_frame.diff().abs().sum(axis=1)
    turnover.iloc[0] = weight_frame.iloc[0].abs().sum()
    returns = prices.pct_change().fillna(0.0).mul(weight_frame).sum(axis=1)
    returns -= turnover * (fee_bps + slippage_bps) / 10000.0
    return returns, turnover, weight_frame


def metric_row(name: str, returns: pd.Series, turnover: pd.Series, qqq_returns: pd.Series,
               scope: str, cost_label: str) -> dict:
    returns = returns.dropna()
    wealth = (1.0 + returns).cumprod()
    monthly = (1.0 + returns).resample("ME").prod() - 1.0
    mdd = max_drawdown(returns)
    cagr = wealth.iloc[-1] ** (252.0 / len(returns)) - 1.0 if len(returns) else math.nan
    return {
        "strategy": name, "scope": scope, "cost_scenario": cost_label,
        "start": str(returns.index.min().date()), "end": str(returns.index.max().date()),
        "n_days": int(len(returns)), "cumulative_return": float(wealth.iloc[-1] - 1.0),
        "cagr": float(cagr), "max_drawdown": float(mdd),
        "recovery_days": recovery_days(returns), "worst_day": float(returns.min()),
        "worst_month": float(monthly.min()), "turnover": float(turnover.reindex(returns.index).sum()),
        "trade_count": int((turnover.reindex(returns.index) > 1e-12).sum()),
        "qqq_down_day_up_rate": float((returns[qqq_returns.reindex(returns.index) < 0] > 0).mean()),
    }


def contributions(prices: pd.DataFrame, weights: dict[str, float], returns: pd.Series) -> list[dict]:
    asset_returns = prices.pct_change().fillna(0.0)
    for symbol, weight in weights.items():
        contribution = asset_returns[symbol] * weight
        yield {
            "strategy": "", "asset": symbol, "weight": weight,
            "contribution_sum": float(contribution.loc[returns.index].sum()),
            "contribution_compounded_proxy": float((1.0 + contribution.loc[returns.index]).prod() - 1.0),
        }


def evaluate(raw: dict[str, pd.DataFrame], output_dir: Path, end: str, errors: dict[str, str]) -> dict[str, str]:
    rows: list[dict] = []
    attribution: list[dict] = []
    coverage = []
    for symbol in ALL_SYMBOLS:
        frame = raw.get(symbol)
        coverage.append({"symbol": symbol, "status": "OK" if frame is not None else "ERROR_OR_EMPTY",
                         "first_readable_date": str(frame.date.min().date()) if frame is not None else None,
                         "last_readable_date": str(frame.date.max().date()) if frame is not None else None,
                         "rows": int(len(frame)) if frame is not None else 0, "error": errors.get(symbol)})
    qqq = raw["US.QQQ"].set_index("date")["close"]
    for name, weights in CANDIDATES.items():
        if any(symbol not in raw for symbol in weights):
            continue
        prices = price_frame(raw, list(weights))
        for fee, slippage, label in COSTS:
            returns, turnover, _ = portfolio_returns(prices, weights, fee, slippage)
            qqq_returns = qqq.pct_change().reindex(returns.index)
            full = returns.loc[FORMAL_START:end]
            if len(full) < 2:
                continue
            rows.append(metric_row(name, full, turnover, qqq_returns,
                                   "FULL_CHRONOLOGICAL_REPLAY", label))
            for year in STRESS_YEARS:
                part = full[full.index.year == year]
                if len(part) > 1:
                    rows.append(metric_row(name, part, turnover, qqq_returns, f"STRESS_{year}", label))
            for year, part in full.groupby(full.index.year):
                rows.append(metric_row(name, part, turnover, qqq_returns, f"YEAR_{year}", label))
            # Chronological rolling forward report: fixed rules, no later-window selection.
            for forward_year in range(2012, 2027, 2):
                forward = full[full.index.year.isin((forward_year, forward_year + 1))]
                train_end = f"{forward_year - 1}-12-31"
                if len(forward) > 1:
                    rows.append(metric_row(name, forward, turnover, qqq_returns,
                                           f"ROLLING_FORWARD_{forward_year}_{forward_year + 1}", label) | {
                                               "train_end": train_end,
                                               "forward_start": str(forward.index.min().date()),
                                           })
            if label == "5bp_fee_5bp_slippage":
                for item in contributions(prices, weights, full):
                    item["strategy"] = name
                    item["cost_scenario"] = label
                    attribution.append(item)
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v07_2026-10-18"
    paths = {key: output_dir / f"{prefix}_{suffix}" for key, suffix in {
        "metrics": "metrics.csv", "attribution": "attribution.csv", "coverage": "coverage.csv",
        "metadata": "metadata.json", "report": "report.md"}.items()}
    pd.DataFrame(rows).to_csv(paths["metrics"], index=False, encoding="utf-8-sig")
    pd.DataFrame(attribution).to_csv(paths["attribution"], index=False, encoding="utf-8-sig")
    pd.DataFrame(coverage).to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "source": "local OpenD only",
        "endpoint": "127.0.0.1:11111", "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ", "end": end},
        "formal_start": FORMAL_START, "rules_frozen_before_replay": True, "next_day_effective": True,
        "candidates": CANDIDATES, "stress_years": STRESS_YEARS,
        "observed_through": "2026-10-16", "observed_2025_2026": True,
        "provider_finality": "UNKNOWN", "timezone_exchange_calendar": "UNKNOWN",
        "oos_status": "NOT_VERIFIED", "trade_execution": "NO", "radar_admission": "BLOCKED",
        "candidate_selection": "PREDECLARED_NO_OPTIMIZATION",
    }
    metadata["sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in (paths["metrics"], paths["attribution"], paths["coverage"])}
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    full = pd.DataFrame(rows)
    summary = full[(full.scope == "FULL_CHRONOLOGICAL_REPLAY") & (full.cost_scenario == COSTS[0][2])]
    lines = [f"- `{r.strategy}`: sample={r.start}—{r.end}, CAGR={r.cagr:.4f}, MDD={r.max_drawdown:.4f}, recovery_days={r.recovery_days}, turnover={r.turnover:.2f}, trades={int(r.trade_count)}"
             for r in summary.itertuples()]
    stress_available = sorted(set(full.loc[full.scope.str.startswith("STRESS_")].scope)) if not full.empty else []
    attribution_lines = []
    if not pd.DataFrame(attribution).empty:
        for strategy in ("B_UPSIDE_HEDGE", "C_BALANCED_COMPOUND"):
            subset = pd.DataFrame(attribution)
            subset = subset[subset.strategy == strategy]
            attribution_lines.append(f"- `{strategy}` asset contribution proxy: " + ", ".join(
                f"{row.asset}={row.contribution_sum:.4f}" for row in subset.itertuples()))
    paths["report"].write_text("\n".join([
        "# STOCK RAZOR Dual-Market Strategy V0.7",
        "", f"正式区间：{FORMAL_START}—{end}；仅使用本机 OpenD 127.0.0.1:11111 K_DAY/RTH/QFQ。",
        "每个候选在回放前固定；持仓按资产首个可读日与共同可读日期自然限制，不回填 ETF 上市前数据。",
        "全部信号只使用已闭合日线，下一交易日生效；成本为 5bp+5bp 与 10bp+10bp。",
        "候选是有限的预声明对照，不做参数搜索或目标函数优化；滚动前向窗口按时间顺序报告。",
        "2025—2026 已被观察过，因此 OOS=NOT_VERIFIED；provider_finality=UNKNOWN；独立交易日历/时区=UNKNOWN。",
        "", "## 正式区间摘要（5bp+5bp）", "", *lines,
        "", "## 资产贡献（简单加权收益贡献代理，5bp+5bp）", "", *attribution_lines,
        "", "## 压力与样本边界", "",
        f"已计算压力窗口：{', '.join(stress_available) if stress_available else 'NONE'}。",
        "B/C 的 DBMF 首个可读日为 2019-05-08，因此 2008 压力表现为 NOT_VERIFIED；不能用 B/C 推断 2008。",
        "IALT 首个可读日为 2025-12-10，因此 D/E 不能与 B/C 的 2019—2026 样本作等价全周期比较。",
        "压力年份、最差日/月、恢复期、换手、交易次数和更高成本敏感性见 metrics.csv。",
        "RADAR_ADMISSION=BLOCKED；PAPER_AUTO_READY=NO；TRADE_EXECUTION=NO。", "",
    ]) + "\n", encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    raw, errors = {}, {}
    try:
        for symbol in ALL_SYMBOLS:
            frame, status = fetch_history(ctx, symbol, args.end)
            if frame is None:
                errors[symbol] = status
            else:
                raw[symbol] = frame
    finally:
        ctx.close()
    if "US.QQQ" not in raw:
        raise RuntimeError(f"required QQQ unavailable; errors={errors}")
    print(json.dumps(evaluate(raw, args.output_dir, args.end, errors), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

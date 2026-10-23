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


DEFAULT_END = "2026-10-16"
SYMBOLS = [
    "US.QQQ", "US.IALT", "US.KMLM", "US.CTA", "US.DBMF", "US.BTAL", "US.TAIL",
    "US.RPAR", "US.SWAN", "US.USMV", "US.SPLV", "US.IEF", "US.TLT", "US.GLDM",
    "US.SGOL", "US.SHV", "US.BIL", "US.SGOV",
]
SEGMENTS = {
    "TRAIN_2020_CRASH": ("2020-01-01", "2022-12-30"),
    "VALIDATION_2023_2024": ("2023-01-01", "2024-12-31"),
    "FINAL_OOS_2025_2026": ("2025-01-01", DEFAULT_END),
}
STRATEGIES = {
    "BTAL_IEF_SHV": {"US.BTAL": 0.40, "US.IEF": 0.35, "US.SHV": 0.25},
    "QQQ_BTAL_IEF_SHV": {"US.QQQ": 0.35, "US.BTAL": 0.25, "US.IEF": 0.25, "US.SHV": 0.15},
    "QQQ_BTAL_GLDM_SHV": {"US.QQQ": 0.35, "US.BTAL": 0.25, "US.GLDM": 0.20, "US.SHV": 0.20},
    "QQQ_TAIL_IEF_SHV": {"US.QQQ": 0.35, "US.TAIL": 0.20, "US.IEF": 0.25, "US.SHV": 0.20},
    "QQQ_RPAR_BTAL_SHV": {"US.QQQ": 0.35, "US.RPAR": 0.25, "US.BTAL": 0.20, "US.SHV": 0.20},
    "QQQ_DBMF_BTAL_SHV": {"US.QQQ": 0.35, "US.DBMF": 0.25, "US.BTAL": 0.20, "US.SHV": 0.20},
    "QQQ_KMLM_BTAL_SHV": {"US.QQQ": 0.35, "US.KMLM": 0.25, "US.BTAL": 0.20, "US.SHV": 0.20},
    "QQQ_USMV_IEF_SHV": {"US.QQQ": 0.35, "US.USMV": 0.25, "US.IEF": 0.20, "US.SHV": 0.20},
    "QQQ_SPLV_IEF_SHV": {"US.QQQ": 0.35, "US.SPLV": 0.25, "US.IEF": 0.20, "US.SHV": 0.20},
    "QQQ_SWAN_BTAL_SHV": {"US.QQQ": 0.35, "US.SWAN": 0.25, "US.BTAL": 0.20, "US.SHV": 0.20},
    "QQQ_DBMF_KMLM_BTAL_SHV": {"US.QQQ": 0.30, "US.DBMF": 0.20, "US.KMLM": 0.20, "US.BTAL": 0.15, "US.SHV": 0.15},
}


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


def max_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    return float((wealth / wealth.cummax() - 1.0).min())


def static_weights(index: pd.Index, selected: dict[str, float]) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=index, columns=list(selected))
    for column, value in selected.items():
        weights[column] = value
    return weights


def lagged_trend_weights(index: pd.DatetimeIndex, qqq: pd.Series) -> pd.DataFrame:
    full_index = qqq.index.union(index).sort_values()
    prices = qqq.reindex(full_index).ffill()
    ma50 = prices.rolling(50, min_periods=50).mean()
    ma200 = prices.rolling(200, min_periods=200).mean()
    up = ((prices > ma50) & (ma50 > ma200)).rolling(3, min_periods=3).sum().eq(3)
    down = ((prices < ma50) & (ma50 < ma200)).rolling(3, min_periods=3).sum().eq(3)
    observed = pd.Series("RANGE", index=full_index, dtype="object")
    observed.loc[up] = "UP"
    observed.loc[down] = "DOWN"
    week_end = pd.Series(full_index, index=full_index).groupby(full_index.to_period("W-FRI")).max()
    weekly = pd.Series(index=full_index, dtype="object")
    weekly.loc[week_end.values] = observed.loc[week_end.values].values
    applied = weekly.ffill().shift(1).fillna("RANGE")
    allocations = {
        "UP": {"US.QQQ": 0.55, "US.BTAL": 0.10, "US.IEF": 0.15, "US.SHV": 0.20},
        "RANGE": {"US.QQQ": 0.35, "US.BTAL": 0.20, "US.IEF": 0.20, "US.SHV": 0.25},
        "DOWN": {"US.QQQ": 0.15, "US.BTAL": 0.30, "US.IEF": 0.25, "US.SHV": 0.30},
    }
    weights = pd.DataFrame(0.0, index=full_index, columns=list(allocations["UP"]))
    for regime, allocation in allocations.items():
        weights.loc[applied.eq(regime), list(allocation)] = list(allocation.values())
    return weights.reindex(index)


def build_returns(prices: pd.DataFrame, weights: pd.DataFrame, fee_bps: float, slippage_bps: float) -> tuple[pd.Series, pd.Series]:
    asset_returns = prices.pct_change().fillna(0.0)
    weights = weights.reindex(prices.index).ffill().fillna(0.0)
    turnover = weights.diff().abs().sum(axis=1)
    turnover.iloc[0] = weights.iloc[0].abs().sum()
    costs = turnover * (fee_bps + slippage_bps) / 10000.0
    return (weights * asset_returns).sum(axis=1) - costs, turnover


def metric_row(name: str, returns: pd.Series, qqq_returns: pd.Series, turnover: pd.Series, segment: str, cost_label: str) -> dict:
    returns = returns.dropna()
    qqq_returns = qqq_returns.reindex(returns.index)
    wealth = (1.0 + returns).cumprod()
    gains = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()
    annualized_return = wealth.iloc[-1] ** (252.0 / len(returns)) - 1.0 if len(returns) else np.nan
    row = {
        "segment": segment, "strategy": name, "cost_scenario": cost_label,
        "sample_start": str(returns.index.min().date()), "sample_end": str(returns.index.max().date()),
        "n_days": int(len(returns)), "cumulative_return": float(wealth.iloc[-1] - 1.0),
        "annualized_return": float(annualized_return), "annualized_volatility": float(returns.std(ddof=1) * math.sqrt(252)) if len(returns) > 1 else np.nan,
        "sharpe": float(returns.mean() / returns.std(ddof=1) * math.sqrt(252)) if len(returns) > 1 and returns.std(ddof=1) else np.nan,
        "max_drawdown": max_drawdown(returns), "calmar": float(annualized_return / abs(max_drawdown(returns))) if max_drawdown(returns) else np.nan,
        "profit_factor": float(gains / losses) if losses else np.nan, "turnover_sum": float(turnover.sum()),
        "turnover_mean_daily": float(turnover.mean()), "positive_day_rate": float((returns > 0).mean()),
        "qqq_up_day_portfolio_up_rate": float((returns[qqq_returns > 0] > 0).mean()) if (qqq_returns > 0).any() else np.nan,
        "qqq_down_day_portfolio_still_up_rate": float((returns[qqq_returns < 0] > 0).mean()) if (qqq_returns < 0).any() else np.nan,
    }
    for threshold in (0.01, 0.02, 0.03):
        mask = qqq_returns <= -threshold
        key = f"qqq_down_{int(threshold * 100)}pct"
        row[f"{key}_days"] = int(mask.sum())
        row[f"{key}_portfolio_up_rate"] = float((returns[mask] > 0).mean()) if mask.any() else np.nan
        row[f"{key}_portfolio_mean_return"] = float(returns[mask].mean()) if mask.any() else np.nan
    return row


def strategy_prices(raw: dict[str, pd.DataFrame], symbols: list[str]) -> pd.DataFrame:
    frames = {code: raw[code].set_index("date")["close"] for code in symbols}
    return pd.concat(frames, axis=1, join="inner").sort_index()


def run(raw: dict[str, pd.DataFrame], output_dir: Path, end: str, errors: dict[str, str]) -> dict[str, str]:
    coverage = []
    for code in SYMBOLS:
        frame = raw.get(code)
        coverage.append({"symbol": code, "status": "OK" if frame is not None else "ERROR_OR_EMPTY", "first_date": str(frame.date.min().date()) if frame is not None else None, "last_date": str(frame.date.max().date()) if frame is not None else None, "rows": int(len(frame)) if frame is not None else 0, "error": errors.get(code)})
    all_summaries, annual_rows, monthly_rows, strategy_meta = [], [], [], {}
    qqq = raw["US.QQQ"].set_index("date")["close"]
    definitions = dict(STRATEGIES)
    definitions["TREND_QQQ_BTAL_IEF_SHV"] = {"US.QQQ": 0.0, "US.BTAL": 0.0, "US.IEF": 0.0, "US.SHV": 0.0}
    for name, definition in definitions.items():
        symbols = list(definition)
        if any(symbol not in raw for symbol in symbols):
            strategy_meta[name] = {"status": "UNAVAILABLE", "missing_symbols": [s for s in symbols if s not in raw]}
            continue
        prices = strategy_prices(raw, symbols)
        weights = static_weights(prices.index, definition) if name != "TREND_QQQ_BTAL_IEF_SHV" else lagged_trend_weights(prices.index, qqq)
        strategy_meta[name] = {"status": "AVAILABLE", "symbols": symbols, "first_common_date": str(prices.index.min().date()), "last_common_date": str(prices.index.max().date()), "common_days": int(len(prices))}
        for segment, (start, stop) in SEGMENTS.items():
            segment_prices = prices.loc[start:stop]
            if len(segment_prices) < 2:
                continue
            segment_weights = weights.reindex(segment_prices.index)
            qqq_returns = qqq.reindex(segment_prices.index).pct_change()
            five_bp_returns = None
            five_bp_turnover = None
            for fee, slippage, label in ((0, 0, "0bp_fee_0bp_slippage"), (5, 5, "5bp_fee_5bp_slippage"), (10, 10, "10bp_fee_10bp_slippage")):
                returns, turnover = build_returns(segment_prices, segment_weights, fee, slippage)
                all_summaries.append(metric_row(name, returns, qqq_returns, turnover, segment, label))
                if label == "5bp_fee_5bp_slippage":
                    five_bp_returns, five_bp_turnover = returns, turnover
            annual = five_bp_returns.to_frame("portfolio_return")
            annual["year"] = annual.index.year
            for year, group in annual.groupby("year"):
                all_summaries.append(metric_row(name, group["portfolio_return"], qqq_returns.reindex(group.index), five_bp_turnover.reindex(group.index), f"{segment}_YEAR_{year}", "5bp_fee_5bp_slippage"))
    summary = pd.DataFrame(all_summaries)
    benchmark_rows = []
    for segment, (start, stop) in SEGMENTS.items():
        qqq_prices = qqq.loc[start:stop]
        qqq_returns = qqq_prices.pct_change().dropna()
        benchmark_rows.append(metric_row("QQQ_BENCHMARK", qqq_returns, qqq_returns, pd.Series(0.0, index=qqq_returns.index), segment, "0bp_fee_0bp_slippage"))
    benchmark = pd.DataFrame(benchmark_rows)
    summary = pd.concat([summary, benchmark], ignore_index=True)
    benchmark_drawdowns = benchmark.set_index("segment")["max_drawdown"].to_dict()
    summary["qqq_benchmark_max_drawdown"] = summary["segment"].map(benchmark_drawdowns)
    summary["drawdown_strictly_less_than_qqq"] = summary["max_drawdown"] > summary["qqq_benchmark_max_drawdown"]
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v03_2026-10-18"
    paths = {key: output_dir / f"{prefix}_{suffix}" for key, suffix in {"summary": "summary.csv", "coverage": "coverage.csv", "metadata": "metadata.json", "report": "report.md"}.items()}
    summary.to_csv(paths["summary"], index=False, encoding="utf-8-sig")
    pd.DataFrame(coverage).to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    meta = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "source": "local Futu/OpenD only", "endpoint": "127.0.0.1:11111", "end_date": end, "query": {"ktype": "K_DAY", "autype": "QFQ", "session": "RTH", "extended_time": False}, "segments": SEGMENTS, "strategy_definitions": STRATEGIES, "candidate_count": len(STRATEGIES), "coverage": coverage, "strategy_meta": strategy_meta, "benchmark": benchmark.to_dict(orient="records"), "provider_finality": "UNKNOWN", "timezone_exchange_calendar": "UNKNOWN", "oos_status": "NOT_VERIFIED", "trade_execution": "NO", "radar_admission": "BLOCKED", "errors": errors}
    paths["metadata"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    meta["sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (paths["summary"], paths["coverage"])}
    paths["metadata"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    final = summary[(summary.segment == "FINAL_OOS_2025_2026") & (summary.cost_scenario == "5bp_fee_5bp_slippage")].copy()
    final = final.sort_values(["max_drawdown", "cumulative_return"], ascending=[False, False])
    report = ["# STOCK RAZOR Dual-Market Strategy V0.3", "", f"- 数据源：本机 OpenD `127.0.0.1:11111`，`K_DAY/RTH/QFQ`，截止 `{end}`；不得将本报告解释为实时、最终性或交易准入证明。", "- 分段固定为：训练/危机 `2020-01-01—2022-12-30`，验证 `2023-01-01—2024-12-31`，最终留出 `2025-01-01—2026-10-16`。", "- 候选集合和权重在回测前固定；没有用最终留出段调参。不同策略按各自真实共同起点计算，不能直接把不同长度样本的收益排名当作结论。", "- `provider_finality=UNKNOWN`、交易日历/时区独立证明 `UNKNOWN`、`OOS=NOT_VERIFIED`、`TRADE_EXECUTION=NO`、`RADAR_ADMISSION=BLOCKED`。", "", "## IALT 与替代品", "", "- IALT 的 OpenD 首个可读日期为 2025-12-10，因此没有把 IALT 填补到 2020—2025，也没有把它用于长期候选排名。", "- 长期替代候选包括 BTAL、DBMF、TAIL、RPAR、SWAN、USMV、SPLV、IEF、GLDM、SHV；KMLM 从 2020-12-02 起可读，CTA 从 2022-03-08 起可读。", "", "## 最终留出段（5bp 费用 + 5bp 滑点）", "", "策略排名请以 summary CSV 和 coverage CSV 为准；这里只列出按最大回撤优先、累计收益次优的候选，不构成事后选择授权。", ""]
    if not final.empty:
        report.extend(f"- `{row.strategy}`：累计 {row.cumulative_return:.2%}，最大回撤 {row.max_drawdown:.2%}，QQQ 下跌日仍上涨率 {row.qqq_down_day_portfolio_still_up_rate:.2%}，样本 {row.sample_start}—{row.sample_end}。" for row in final.head(8).itertuples())
    report += ["", "## 失败或不可比项", "", "- IALT 仅有 2025-12-10 之后数据；CTA 不能覆盖完整 2020—2021；KMLM 不能覆盖 2020-12-01 之前。它们不得被回填、伪造或与长历史策略直接排名。", "- 成本模型只含按权重变动计算的费用和滑点，不含价差冲击、税费、跟踪误差或实际成交；因此交易和 Paper 结果仍为 UNKNOWN。", "", "## 文件", ""]
    report.extend(f"- `{path.name}`" for path in paths.values())
    paths["report"].write_text("\n".join(report) + "\n", encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    raw, errors = {}, {}
    try:
        for code in SYMBOLS:
            frame, status = fetch_history(ctx, code, args.end)
            if frame is None:
                errors[code] = status
            else:
                raw[code] = frame
    finally:
        ctx.close()
    if "US.QQQ" not in raw:
        raise RuntimeError(f"required OpenD benchmark unavailable; errors={errors}")
    print(json.dumps(run(raw, args.output_dir, args.end, errors), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

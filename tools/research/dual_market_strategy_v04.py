from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from tools.research.dual_market_strategy_v03 import (
        DEFAULT_END,
        SYMBOLS,
        STRATEGIES,
        build_returns,
        fetch_history,
        lagged_trend_weights,
        max_drawdown,
        strategy_prices,
    )
except ModuleNotFoundError:
    from dual_market_strategy_v03 import (
        DEFAULT_END,
        SYMBOLS,
        STRATEGIES,
        build_returns,
        fetch_history,
        lagged_trend_weights,
        max_drawdown,
        strategy_prices,
    )


FOCUS_STRATEGIES = {
    "QQQ_TAIL_IEF_SHV",
    "QQQ_USMV_IEF_SHV",
    "QQQ_DBMF_BTAL_SHV",
    "QQQ_KMLM_BTAL_SHV",
    "QQQ_DBMF_KMLM_BTAL_SHV",
    "TREND_QQQ_BTAL_IEF_SHV",
}
ROLLING_FORWARD_YEARS = range(2021, 2027)


def strategy_definitions() -> dict[str, dict[str, float]]:
    definitions = {name: value for name, value in STRATEGIES.items() if name in FOCUS_STRATEGIES}
    definitions["TREND_QQQ_BTAL_IEF_SHV"] = {
        "US.QQQ": 0.0,
        "US.BTAL": 0.0,
        "US.IEF": 0.0,
        "US.SHV": 0.0,
    }
    return definitions


def annual_metrics(returns: pd.Series, qqq_returns: pd.Series, turnover: pd.Series, strategy: str, cost_label: str) -> list[dict]:
    rows = []
    frame = pd.DataFrame({"returns": returns, "qqq": qqq_returns, "turnover": turnover}).dropna(subset=["returns"])
    for year, group in frame.groupby(frame.index.year):
        wealth = (1.0 + group["returns"]).cumprod()
        rows.append({
            "strategy": strategy,
            "year": int(year),
            "cost_scenario": cost_label,
            "n_days": int(len(group)),
            "cumulative_return": float(wealth.iloc[-1] - 1.0),
            "max_drawdown": max_drawdown(group["returns"]),
            "qqq_up_day_portfolio_up_rate": float((group.loc[group["qqq"] > 0, "returns"] > 0).mean()) if (group["qqq"] > 0).any() else np.nan,
            "qqq_down_day_portfolio_still_up_rate": float((group.loc[group["qqq"] < 0, "returns"] > 0).mean()) if (group["qqq"] < 0).any() else np.nan,
            "turnover_sum": float(group["turnover"].sum()),
            "turnover_mean_daily": float(group["turnover"].mean()),
        })
    return rows


def pressure_metrics(returns: pd.Series, qqq_returns: pd.Series, strategy: str, cost_label: str) -> list[dict]:
    frame = pd.DataFrame({"portfolio": returns, "qqq": qqq_returns}).dropna()
    rows = []
    for year, group in frame.groupby(frame.index.year):
        for threshold in (0.01, 0.02, 0.03):
            mask = group["qqq"] <= -threshold
            rows.append({
                "strategy": strategy,
                "year": int(year),
                "threshold": threshold,
                "cost_scenario": cost_label,
                "days": int(mask.sum()),
                "portfolio_up_rate": float((group.loc[mask, "portfolio"] > 0).mean()) if mask.any() else np.nan,
                "portfolio_mean_return": float(group.loc[mask, "portfolio"].mean()) if mask.any() else np.nan,
                "portfolio_worst_return": float(group.loc[mask, "portfolio"].min()) if mask.any() else np.nan,
            })
    return rows


def tail_risk_decomposition(prices: pd.DataFrame, weights: pd.DataFrame) -> list[dict]:
    returns = prices.pct_change()
    qqq = returns["US.QQQ"]
    rows = []
    for symbol in weights.columns:
        asset = returns[symbol].dropna()
        aligned = pd.DataFrame({"asset": asset, "qqq": qqq}, index=asset.index).dropna()
        down = aligned[aligned["qqq"] < 0]
        rows.append({
            "asset": symbol,
            "weight": float(weights[symbol].iloc[-1]),
            "full_sample_mean_daily_return": float(asset.mean()),
            "full_sample_volatility": float(asset.std(ddof=1)),
            "qqq_correlation": float(aligned["asset"].corr(aligned["qqq"])),
            "qqq_down_day_mean_return": float(down["asset"].mean()) if not down.empty else np.nan,
            "qqq_down_day_positive_rate": float((down["asset"] > 0).mean()) if not down.empty else np.nan,
            "weighted_mean_daily_contribution": float((asset * weights[symbol].reindex(asset.index).ffill()).mean()),
        })
    return rows


def rolling_forward_metrics(returns: pd.Series, qqq_returns: pd.Series, turnover: pd.Series, strategy: str, cost_label: str) -> list[dict]:
    frame = pd.DataFrame({"returns": returns, "qqq": qqq_returns, "turnover": turnover}).dropna(subset=["returns"])
    rows = []
    for year in ROLLING_FORWARD_YEARS:
        train = frame.loc[:f"{year - 1}-12-31"]
        forward = frame.loc[f"{year}-01-01":f"{year}-12-31"]
        if train.empty or forward.empty:
            continue
        wealth = (1.0 + forward["returns"]).cumprod()
        rows.append({
            "strategy": strategy,
            "forward_year": year,
            "train_end": str(train.index.max().date()),
            "forward_start": str(forward.index.min().date()),
            "forward_end": str(forward.index.max().date()),
            "cost_scenario": cost_label,
            "train_days": int(len(train)),
            "forward_days": int(len(forward)),
            "forward_return": float(wealth.iloc[-1] - 1.0),
            "forward_max_drawdown": max_drawdown(forward["returns"]),
            "qqq_forward_return": float((1.0 + forward["qqq"]).cumprod().iloc[-1] - 1.0),
            "forward_turnover_sum": float(forward["turnover"].sum()),
        })
    return rows


def run(raw: dict[str, pd.DataFrame], output_dir: Path, end: str, errors: dict[str, str]) -> dict[str, str]:
    definitions = strategy_definitions()
    qqq = raw["US.QQQ"].set_index("date")["close"]
    all_annual, all_pressure, all_rolling, all_decomposition, strategy_meta = [], [], [], [], {}
    for name, definition in definitions.items():
        symbols = ["US.QQQ", "US.BTAL", "US.IEF", "US.SHV"] if name.startswith("TREND_") else list(definition)
        if any(symbol not in raw for symbol in symbols):
            strategy_meta[name] = {"status": "UNAVAILABLE", "missing_symbols": [s for s in symbols if s not in raw]}
            continue
        prices = strategy_prices(raw, symbols)
        weights = lagged_trend_weights(prices.index, qqq) if name.startswith("TREND_") else pd.DataFrame({s: definition[s] for s in symbols}, index=prices.index)
        strategy_meta[name] = {"status": "AVAILABLE", "symbols": symbols, "first_common_date": str(prices.index.min().date()), "last_common_date": str(prices.index.max().date()), "common_days": int(len(prices))}
        if name == "QQQ_TAIL_IEF_SHV":
            all_decomposition.extend(tail_risk_decomposition(prices, weights))
        for fee, slippage, label in ((5, 5, "5bp_fee_5bp_slippage"),):
            returns, turnover = build_returns(prices, weights, fee, slippage)
            qqq_returns = qqq.reindex(prices.index).pct_change()
            annual_rows = annual_metrics(returns, qqq_returns, turnover, name, label)
            for row in annual_rows:
                row["sample_total_turnover"] = float(turnover.sum())
                row["sample_mean_daily_turnover"] = float(turnover.mean())
            all_annual.extend(annual_rows)
            all_pressure.extend(pressure_metrics(returns, qqq_returns, name, label))
            all_rolling.extend(rolling_forward_metrics(returns, qqq_returns, turnover, name, label))

    qqq_prices = raw["US.QQQ"].set_index("date")["close"]
    qqq_returns = qqq_prices.pct_change()
    qqq_turnover = pd.Series(0.0, index=qqq_returns.index)
    all_annual.extend(annual_metrics(qqq_returns, qqq_returns, qqq_turnover, "QQQ_BENCHMARK", "0bp_fee_0bp_slippage"))
    all_pressure.extend(pressure_metrics(qqq_returns, qqq_returns, "QQQ_BENCHMARK", "0bp_fee_0bp_slippage"))
    all_rolling.extend(rolling_forward_metrics(qqq_returns, qqq_returns, qqq_turnover, "QQQ_BENCHMARK", "0bp_fee_0bp_slippage"))

    prefix = "stock_razor_dual_market_strategy_v04_2026-10-18"
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {key: output_dir / f"{prefix}_{suffix}" for key, suffix in {
        "annual": "annual.csv", "pressure": "pressure.csv", "rolling": "rolling_forward.csv",
        "decomposition": "tail_decomposition.csv", "coverage": "coverage.csv", "metadata": "metadata.json", "report": "report.md",
    }.items()}
    coverage = [{"symbol": code, "status": "OK" if code in raw else "ERROR_OR_EMPTY", "first_date": str(raw[code].date.min().date()) if code in raw else None, "last_date": str(raw[code].date.max().date()) if code in raw else None, "rows": int(len(raw[code])) if code in raw else 0, "error": errors.get(code)} for code in SYMBOLS]
    pd.DataFrame(all_annual).to_csv(paths["annual"], index=False, encoding="utf-8-sig")
    pd.DataFrame(all_pressure).to_csv(paths["pressure"], index=False, encoding="utf-8-sig")
    pd.DataFrame(all_rolling).to_csv(paths["rolling"], index=False, encoding="utf-8-sig")
    pd.DataFrame(all_decomposition).to_csv(paths["decomposition"], index=False, encoding="utf-8-sig")
    pd.DataFrame(coverage).to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    meta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "local Futu/OpenD only", "endpoint": "127.0.0.1:11111", "end_date": end,
        "query": {"ktype": "K_DAY", "autype": "QFQ", "session": "RTH", "extended_time": False},
        "cost_model": {"strategy_fee_bps": 5, "strategy_slippage_bps": 5, "benchmark_fee_bps": 0, "benchmark_slippage_bps": 0},
        "focus_strategies": sorted(FOCUS_STRATEGIES), "strategy_definitions": definitions,
        "coverage": coverage, "strategy_meta": strategy_meta,
        "provider_finality": "UNKNOWN", "timezone_exchange_calendar": "UNKNOWN",
        "oos_status": "NOT_VERIFIED", "rolling_forward_status": "FIXED_RULE_FORWARD_ONLY",
        "observed_2025_2026": True, "trade_execution": "NO", "radar_admission": "BLOCKED", "errors": errors,
    }
    for path in paths.values():
        if path.suffix == ".csv":
            meta.setdefault("sha256", {})[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    paths["metadata"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    annual = pd.DataFrame(all_annual)
    report = [
        "# STOCK RAZOR Dual-Market Strategy V0.4",
        "",
        f"- 数据源：本机 OpenD `127.0.0.1:11111`，仅 `K_DAY/RTH/QFQ`，截止 `{end}`；所有日期按已返回日线处理。",
        "- 比较重点：`QQQ_TAIL_IEF_SHV` 低回撤基准、`QQQ_USMV_IEF_SHV` 收益平衡基准，以及事先固定的 DBMF/KMLM/BTAL 和滞后一周趋势防御候选。",
        "- 2025—2026 已在 V0.3 被观察，本报告不称其为全新盲测；滚动表是固定规则的前向年度表现，不是重新调参后的 OOS 认证。",
        "- `provider_finality=UNKNOWN`、独立交易日历/时区证明 `UNKNOWN`、`OOS=NOT_VERIFIED`、`TRADE_EXECUTION=NO`、`RADAR_ADMISSION=BLOCKED`。",
        "",
        "## TAIL 与 USMV 的解释边界",
        "",
        "- TAIL 的低回撤来自其自身与 QQQ 的低相关/下跌日对冲特征叠加较高 SHV/IEF 权重；其期权保险成本和较低 QQQ 权重会牺牲上涨阶段参与度。`tail_decomposition.csv` 只支持历史相关、下跌日均值和贡献描述，不证明未来因果或保护效果。",
        "- USMV 仍保留较高 QQQ 相关风险，因此通常保留更多上涨参与度，但不能被称作尾部对冲；应以逐年和压力表中的实际结果为准。",
        "",
        "## 文件",
        "",
    ]
    report.extend(f"- `{path.name}`" for path in paths.values())
    paths["report"].write_text("\n".join(report) + "\n", encoding="utf-8")
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

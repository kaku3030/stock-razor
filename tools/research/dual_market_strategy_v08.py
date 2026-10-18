"""Research-only QQQ/SCHD/gold ETF comparison using local OpenD daily bars.

Rules are fixed before the replay. Prices are local OpenD K_DAY/RTH/QFQ data;
QFQ dividend semantics are not independently verified, so results are labeled
price-return sensitivity rather than proven total-return performance.
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


FORMAL_START = "2006-10-04"
DEFAULT_END = "2026-10-16"
COSTS = ((5, 5, "5bp_fee_5bp_slippage"), (10, 10, "10bp_fee_10bp_slippage"))
STRESS_WINDOWS = (2008, 2018, 2020, 2022, 2025)
OFFICIAL_INCEPTION_DATES = {
    "US.QQQ": "1999-03-10",
    "US.SCHD": "2011-10-20",
    "US.GLD": "2004-11-18",
    "US.IAU": "2005-01-21",
    "US.GLDM": "2018-06-25",
}
OFFICIAL_TRADING_DATES = {
    "US.QQQ": "1999-03-10",
    "US.SCHD": "2011-10-20",
    "US.GLD": "2004-11-18",
    "US.IAU": "2005-01-21",
    "US.GLDM": "2018-06-26",
}
OFFICIAL_SOURCES = {
    "US.QQQ": "https://www.invesco.com/us/financial-products/etfs/product-detail?audienceType=investors&productId=QQQ&ticker=QQQ",
    "US.SCHD": "https://www.schwabassetmanagement.com/products/schd",
    "US.GLD": "https://www.ssga.com/us/en/institutional/etfs/spdr-gold-shares-gld",
    "US.IAU": "https://www.ishares.com/us/products/239561/ishares-gold-trust-fund",
    "US.GLDM": "https://www.ssga.com/us/en/intermediary/etfs/spdr-gold-minishares-gldm",
}

# Frozen before replay: finite comparisons, not an optimizer.
CANDIDATES = {
    "QQQ_SCHD_GLD_50_30_20": {"US.QQQ": .50, "US.SCHD": .30, "US.GLD": .20},
    "QQQ_SCHD_GLD_40_30_30": {"US.QQQ": .40, "US.SCHD": .30, "US.GLD": .30},
    "QQQ_SCHD_GLD_60_20_20": {"US.QQQ": .60, "US.SCHD": .20, "US.GLD": .20},
    "QQQ_ONLY": {"US.QQQ": 1.0},
    "LONG_GOLD_50_50": {"US.QQQ": .50, "US.GLD": .50},
    # Long-history control with no SCHD; the modern comparison remains separate.
    "LONG_GOLD_40_30_30": {"US.QQQ": .40, "US.GLD": .30, "US.SHV": .30},
    # V0.7 same-window controls, reproduced here so the comparison is self-contained.
    "B_UPSIDE_HEDGE": {"US.QQQ": .35, "US.DBMF": .25, "US.BTAL": .20, "US.SHV": .20},
    "C_BALANCED_COMPOUND": {"US.QQQ": .50, "US.DBMF": .20, "US.BTAL": .10, "US.IEF": .20},
    "F_BALANCED_DEFENSIVE": {"US.QQQ": .45, "US.DBMF": .15, "US.BTAL": .15, "US.IEF": .25},
}
ALL_SYMBOLS = sorted({symbol for weights in CANDIDATES.values() for symbol in weights} | {
    "US.IAU", "US.GLDM"
})


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


def recovery_days(returns: pd.Series) -> float:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    peak = wealth.cummax()
    trough = (wealth / peak - 1.0).idxmin()
    recovered = wealth.loc[trough:][wealth.loc[trough:] >= peak.loc[trough]]
    if recovered.empty:
        return math.nan
    return float(wealth.index.get_loc(recovered.index[0]) - wealth.index.get_loc(trough))


def price_frame(raw: dict[str, pd.DataFrame], symbols: list[str]) -> pd.DataFrame:
    return pd.concat({code: raw[code].set_index("date")["close"] for code in symbols}, axis=1, join="inner").sort_index()


def monthly_rebalanced_returns(prices: pd.DataFrame, weights: dict[str, float], fee_bps: float,
                               slippage_bps: float) -> tuple[pd.Series, pd.Series]:
    asset_returns = prices.pct_change().fillna(0.0)
    target = pd.Series(weights, dtype=float)
    holdings = target.copy()
    values = []
    turnovers = []
    previous_month = None
    for date, daily in asset_returns.iterrows():
        month = (date.year, date.month)
        turnover = 0.0
        if previous_month is None:
            turnover = float(target.abs().sum())
            holdings = target.copy()
        elif month != previous_month:
            total = float(holdings.sum())
            current = holdings / total if total else target
            turnover = float((target - current).abs().sum())
            holdings = target * (1.0 - turnover * (fee_bps + slippage_bps) / 10000.0)
        gross = float((holdings * (1.0 + daily)).sum())
        start = float(holdings.sum())
        values.append(gross / start - 1.0 if start else 0.0)
        turnovers.append(turnover)
        holdings = holdings * (1.0 + daily)
        previous_month = month
    return pd.Series(values, index=asset_returns.index), pd.Series(turnovers, index=asset_returns.index)


def metric_row(name: str, returns: pd.Series, turnover: pd.Series, qqq_returns: pd.Series,
               scope: str, cost_label: str) -> dict:
    returns = returns.dropna()
    wealth = (1.0 + returns).cumprod()
    monthly = (1.0 + returns).resample("ME").prod() - 1.0
    mdd = max_drawdown(returns)
    cagr = wealth.iloc[-1] ** (252.0 / len(returns)) - 1.0 if len(returns) else math.nan
    sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)) if returns.std(ddof=1) else math.nan
    return {
        "strategy": name, "scope": scope, "cost_scenario": cost_label,
        "start": str(returns.index.min().date()), "end": str(returns.index.max().date()),
        "n_days": int(len(returns)), "cumulative_return": float(wealth.iloc[-1] - 1.0),
        "cagr": float(cagr), "max_drawdown": float(mdd),
        "recovery_days": recovery_days(returns), "calmar": float(cagr / abs(mdd)) if mdd else math.nan,
        "sharpe": sharpe, "worst_day": float(returns.min()), "worst_month": float(monthly.min()),
        "monthly_turnover": float(turnover.reindex(returns.index).sum()),
        "rebalance_count": int((turnover.reindex(returns.index) > 1e-12).sum()),
        "qqq_up_day_follow_rate": float((returns[qqq_returns.reindex(returns.index) > 0] > 0).mean()),
        "qqq_down_day_countertrend_up_rate": float((returns[qqq_returns.reindex(returns.index) < 0] > 0).mean()),
    }


def evaluate(raw: dict[str, pd.DataFrame], output_dir: Path, end: str, errors: dict[str, str]) -> dict[str, str]:
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
    rows = []
    if "US.QQQ" not in raw:
        raise RuntimeError("required QQQ unavailable")
    qqq_all = raw["US.QQQ"].set_index("date")["close"].pct_change()
    for name, weights in CANDIDATES.items():
        if any(symbol not in raw for symbol in weights):
            continue
        prices = price_frame(raw, list(weights))
        for fee, slippage, label in COSTS:
            returns, turnover = monthly_rebalanced_returns(prices, weights, fee, slippage)
            full = returns.loc[FORMAL_START:end]
            if len(full) < 2:
                continue
            qqq_returns = qqq_all.reindex(full.index)
            scopes = [("FULL_CHRONOLOGICAL_REPLAY", full)]
            modern = full.loc["2019-05-08":end]
            if len(modern) > 1:
                scopes.append(("MODERN_COMMON_2019_05_08_2026_10_16", modern))
            for scope, part in scopes:
                rows.append(metric_row(name, part, turnover, qqq_returns, scope, label))
                for year in STRESS_WINDOWS:
                    stress = part[part.index.year == year]
                    if len(stress) > 1:
                        rows.append(metric_row(name, stress, turnover, qqq_returns, f"{scope}_STRESS_{year}", label))
                if scope == "FULL_CHRONOLOGICAL_REPLAY":
                    for year, year_part in part.groupby(part.index.year):
                        rows.append(metric_row(name, year_part, turnover, qqq_returns, f"YEAR_{year}", label))
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v08_2026-10-18"
    paths = {key: output_dir / f"{prefix}_{suffix}" for key, suffix in {
        "metrics": "metrics.csv", "coverage": "coverage.csv", "metadata": "metadata.json", "report": "report.md"}.items()}
    pd.DataFrame(rows).to_csv(paths["metrics"], index=False, encoding="utf-8-sig")
    pd.DataFrame(coverage).to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "source": "local OpenD only",
        "endpoint": "127.0.0.1:11111", "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ", "end": end},
        "formal_start": FORMAL_START, "rules_frozen_before_replay": True, "next_day_effective": True,
        "monthly_rebalance": "first_available_trading_day_of_calendar_month_close_to_close_proxy",
        "candidates": CANDIDATES, "stress_windows": STRESS_WINDOWS,
        "official_inception_dates": OFFICIAL_INCEPTION_DATES,
        "official_trading_dates": OFFICIAL_TRADING_DATES,
        "official_sources": OFFICIAL_SOURCES,
        "observed_through": end, "provider_finality": "UNKNOWN", "timezone_exchange_calendar": "UNKNOWN",
        "qfq_dividend_semantics": "UNKNOWN", "return_type": "PRICE_RETURN_SENSITIVITY_NOT_PROVEN_TOTAL_RETURN",
        "oos_status": "NOT_VERIFIED", "trade_execution": "NO", "radar_admission": "BLOCKED",
        "candidate_selection": "PREDECLARED_NO_OPTIMIZATION",
    }
    metadata["sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (paths["metrics"], paths["coverage"])}
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    full = pd.DataFrame(rows)
    summary = full[(full.scope == "FULL_CHRONOLOGICAL_REPLAY") & (full.cost_scenario == COSTS[0][2])]
    modern_summary = full[(full.scope == "MODERN_COMMON_2019_05_08_2026_10_16") & (full.cost_scenario == COSTS[0][2])]
    lines = [f"- `{r.strategy}`: {r.start}—{r.end}, CAGR={r.cagr:.2%}, MDD={r.max_drawdown:.2%}, recovery={r.recovery_days}, Calmar={r.calmar:.2f}, Sharpe={r.sharpe:.2f}, monthly turnover={r.monthly_turnover:.2f}" for r in summary.itertuples()]
    coverage_lines = [f"- `{row['symbol']}`: readable={row['first_readable_date']}—{row['last_readable_date']}; official inception={row['official_inception_date']}; official trading={row['official_trading_date']}" for row in coverage]
    paths["report"].write_text("\n".join([
        "# STOCK RAZOR Dual-Market Strategy V0.8", "",
        f"正式区间：{FORMAL_START}—{end}；仅使用本机 OpenD 127.0.0.1:11111 K_DAY/RTH/QFQ。",
        "候选权重在回放前固定；只使用闭合日线，月度再平衡按每月首个可读交易日的收盘近似，交易成本为 5bp+5bp 与 10bp+10bp。",
        "SCHD 只在真实共同可读日期参与；长期体系不使用 SCHD 的 2006—2010 假历史。", "",
        "## 5bp+5bp 全区间摘要", "", *lines, "",
        "## 2019-05-08—2026-10-16 同窗口摘要（5bp+5bp）", "",
        *[f"- `{r.strategy}`: CAGR={r.cagr:.2%}, MDD={r.max_drawdown:.2%}, recovery={r.recovery_days}, Calmar={r.calmar:.2f}, Sharpe={r.sharpe:.2f}" for r in modern_summary.itertuples()], "",
        "## 覆盖矩阵", "", *coverage_lines, "",
        "## 口径与边界", "", "OpenD QFQ 的股息/总回报语义未由独立官方证据证实；结果是价格收益敏感性，不得冒充含股息总收益。",
        "GLD/IAU/GLDM 的官方日期与 OpenD 首个可读日分别报告，不以 GLDM 较晚上市日回填 GLD/IAU；官方来源已写入 metadata.json。",
        "现代体系应按 SCHD 可读后的共同窗口与 B/C/F 比较；老资产长期体系单独报告。2025—2026 已观察，OOS=NOT_VERIFIED。",
        "SCHD 组合的 2008 压力为 NOT_VERIFIED；2008 只能由不含 SCHD 的真实可读长期对照报告，不能移植到 SCHD 组合。2018 对 SCHD 组合可计算。",
        "provider_finality=UNKNOWN；timezone_exchange_calendar=UNKNOWN；RADAR_ADMISSION=BLOCKED；PAPER_AUTO_READY=NO；TRADE_EXECUTION=NO。",
        "详细年度、压力窗口、跟涨/逆势率、最差日/月、换手和成本敏感性见 metrics.csv。", "",
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
    print(json.dumps(evaluate(raw, args.output_dir, args.end, errors), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

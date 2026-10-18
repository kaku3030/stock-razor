"""Bounded V0.6 dual-market research replay.

Rules are frozen before replay. Signals use only closed observations and the
resulting weights apply on the next available bar. This module is research
only; it does not qualify a provider, Radar, Paper, or trading runtime.
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

try:
    from tools.research.dual_market_strategy_v03 import (
        DEFAULT_END, build_returns, fetch_history, max_drawdown, strategy_prices,
    )
except ModuleNotFoundError:
    from dual_market_strategy_v03 import (
        DEFAULT_END, build_returns, fetch_history, max_drawdown, strategy_prices,
    )


FORMAL_START = "2006-10-04"
COSTS = ((5, 5, "5bp_fee_5bp_slippage"), (10, 10, "10bp_fee_10bp_slippage"))
STRATEGIES = {
    "A_LOW_DRAWDOWN": {"US.QQQ": .20, "US.IEF": .40, "US.TLT": .40},
    "B_UPSIDE_HEDGE": {"US.QQQ": .35, "US.DBMF": .25, "US.BTAL": .20, "US.SHV": .20},
    "C_BALANCED_COMPOUND": {"US.QQQ": .50, "US.DBMF": .20, "US.BTAL": .10, "US.IEF": .20},
}
PHASES = {
    "2006_2011": ("2006-10-04", "2011-12-31"),
    "2012_2017": ("2012-01-06", "2017-04-05"),
    "2017_2019": ("2017-04-06", "2019-05-07"),
    "2019_2022": ("2019-05-08", "2022-12-30"),
    "2023_2024": ("2023-01-01", "2024-12-31"),
    "2025_2026": ("2025-01-01", DEFAULT_END),
}
ALL_SYMBOLS = sorted({symbol for weights in STRATEGIES.values() for symbol in weights} | {"US.QQQ"})


def recovery_days(returns: pd.Series) -> float:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    peak = wealth.cummax()
    trough = (wealth / peak - 1.0).idxmin()
    target = peak.loc[trough]
    recovered = wealth.loc[trough:][wealth.loc[trough:] >= target]
    return float(wealth.index.get_loc(recovered.index[0]) - wealth.index.get_loc(trough)) if not recovered.empty else math.nan


def low_drawdown_weights(index: pd.DatetimeIndex, qqq: pd.Series) -> pd.DataFrame:
    """Fixed 200-day trend/8% drawdown exit, lagged one bar."""
    price = qqq.reindex(index).ffill()
    peak = price.rolling(60, min_periods=60).max()
    defensive = ((price < price.rolling(200, min_periods=200).mean()) |
                 (price / peak - 1.0 <= -0.08)).shift(1).fillna(False)
    weights = pd.DataFrame({"US.QQQ": .20, "US.IEF": .40, "US.TLT": .40}, index=index)
    weights.loc[defensive.astype(bool), ["US.QQQ", "US.IEF", "US.TLT"]] = [.0, .60, .40]
    return weights


def metric_row(name: str, returns: pd.Series, qqq_returns: pd.Series, turnover: pd.Series,
               scope: str, cost_label: str) -> dict:
    returns = returns.dropna()
    qqq_returns = qqq_returns.reindex(returns.index)
    wealth = (1.0 + returns).cumprod()
    mdd = max_drawdown(returns)
    cagr = wealth.iloc[-1] ** (252.0 / len(returns)) - 1.0 if len(returns) else math.nan
    monthly = (1.0 + returns).resample("ME").prod() - 1.0
    return {
        "strategy": name, "scope": scope, "cost_scenario": cost_label,
        "start": str(returns.index.min().date()), "end": str(returns.index.max().date()),
        "n_days": int(len(returns)), "return": float(wealth.iloc[-1] - 1.0),
        "cagr": float(cagr), "max_drawdown": float(mdd),
        "calmar": float(cagr / abs(mdd)) if mdd else math.nan,
        "recovery_days": recovery_days(returns),
        "worst_day": float(returns.min()), "worst_month": float(monthly.min()) if len(monthly) else math.nan,
        "turnover": float(turnover.reindex(returns.index).sum()),
        "trade_count": int((turnover.reindex(returns.index) > 1e-12).sum()),
        "qqq_up_day_follow_rate": float((returns[qqq_returns > 0] > 0).mean()) if (qqq_returns > 0).any() else math.nan,
        "qqq_down_day_up_rate": float((returns[qqq_returns < 0] > 0).mean()) if (qqq_returns < 0).any() else math.nan,
    }


def evaluate(raw: dict[str, pd.DataFrame], output_dir: Path, end: str,
             errors: dict[str, str]) -> dict[str, str]:
    qqq = raw["US.QQQ"].set_index("date")["close"]
    rows: list[dict] = []
    coverage = []
    for symbol in ALL_SYMBOLS:
        frame = raw.get(symbol)
        coverage.append({"symbol": symbol, "status": "OK" if frame is not None else "ERROR_OR_EMPTY",
                         "first_readable_date": str(frame.date.min().date()) if frame is not None else None,
                         "last_readable_date": str(frame.date.max().date()) if frame is not None else None,
                         "rows": int(len(frame)) if frame is not None else 0, "error": errors.get(symbol)})
    for name, definition in STRATEGIES.items():
        if any(symbol not in raw for symbol in definition):
            continue
        prices = strategy_prices(raw, list(definition))
        weights = (low_drawdown_weights(prices.index, qqq) if name == "A_LOW_DRAWDOWN"
                   else pd.DataFrame(definition, index=prices.index))
        for fee, slippage, label in COSTS:
            returns, turnover = build_returns(prices, weights, fee, slippage)
            qqq_returns = qqq.reindex(returns.index).pct_change()
            for scope, (start, stop) in PHASES.items():
                part = returns.loc[start:stop]
                if len(part) < 2:
                    continue
                rows.append(metric_row(name, part, qqq_returns, turnover, scope, label))
            for year, part in returns.loc[FORMAL_START:end].groupby(returns.loc[FORMAL_START:end].index.year):
                rows.append(metric_row(name, part, qqq_returns, turnover, f"YEAR_{year}", label))
            # Chronological walk-forward evidence: no parameter is selected from a later window.
            rows.append(metric_row(name, returns.loc[FORMAL_START:end], qqq_returns, turnover,
                                   "FULL_CHRONOLOGICAL_REPLAY", label))
    qqq_returns = qqq.pct_change()
    rows.append(metric_row("QQQ_BENCHMARK", qqq_returns.loc[FORMAL_START:end], qqq_returns,
                           pd.Series(0.0, index=qqq_returns.index), "FULL_CHRONOLOGICAL_REPLAY", "0bp"))
    for year, part in qqq_returns.loc[FORMAL_START:end].groupby(qqq_returns.loc[FORMAL_START:end].index.year):
        rows.append(metric_row("QQQ_BENCHMARK", part, qqq_returns,
                               pd.Series(0.0, index=part.index), f"YEAR_{year}", "0bp"))
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v06_2026-10-18"
    paths = {key: output_dir / f"{prefix}_{suffix}" for key, suffix in {
        "metrics": "metrics.csv", "coverage": "coverage.csv", "metadata": "metadata.json", "report": "report.md"}.items()}
    pd.DataFrame(rows).to_csv(paths["metrics"], index=False, encoding="utf-8-sig")
    pd.DataFrame(coverage).to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "source": "local OpenD only",
        "endpoint": "127.0.0.1:11111", "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ", "end": end},
        "formal_start": FORMAL_START, "rules_frozen_before_replay": True,
        "next_day_effective": True, "strategies": STRATEGIES, "phases": PHASES,
        "provider_finality": "UNKNOWN", "timezone_exchange_calendar": "UNKNOWN",
        "oos_status": "NOT_VERIFIED", "trade_execution": "NO", "radar_admission": "BLOCKED",
    }
    metadata["sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in (paths["metrics"], paths["coverage"])}
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    full = [row for row in rows if row["scope"] == "FULL_CHRONOLOGICAL_REPLAY" and row["cost_scenario"] == "5bp_fee_5bp_slippage"]
    summary_lines = [
        f"- `{row['strategy']}`: return={row['return']:.4f}, CAGR={row['cagr']:.4f}, MDD={row['max_drawdown']:.4f}, Calmar={row['calmar']:.4f}"
        for row in full
    ]
    paths["report"].write_text("\n".join([
        "# STOCK RAZOR Dual-Market Strategy V0.6",
        "", f"正式研究区间：{FORMAL_START}—{end}；更早区间为 NOT_VERIFIED。",
        "策略 A/B/C 在读取数据前固定，信号只使用前一已闭合 bar，权重下一交易日生效。",
        "按 5bp+5bp 与 10bp+10bp 两个成本场景，分别输出阶段、完整时间序列和 QQQ 同涨/逆势指标。",
        "前向评估仅按时间顺序切窗，不在后续窗口选择参数；因此不构成 OOS 证明。",
        "provider_finality=UNKNOWN；独立交易日历/时区=UNKNOWN；OOS=NOT_VERIFIED；TRADE_EXECUTION=NO；RADAR_ADMISSION=BLOCKED。",
        "", "## 完整正式区间摘要（5bp+5bp）", "", *summary_lines,
        "", "输出文件：", *[f"- `{path.name}`" for path in paths.values()], "",
    ]) + "\n", encoding="utf-8")
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

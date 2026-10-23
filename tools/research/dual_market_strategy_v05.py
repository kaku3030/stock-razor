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
        DEFAULT_END, fetch_history, build_returns, max_drawdown, strategy_prices,
    )
except ModuleNotFoundError:
    from dual_market_strategy_v03 import (
        DEFAULT_END, fetch_history, build_returns, max_drawdown, strategy_prices,
    )

ETF_SYMBOLS = ["US.QQQ", "US.SPY", "US.TLT", "US.IEF", "US.SHV", "US.GLDM", "US.DBMF", "US.BTAL", "US.TAIL", "US.USMV"]
PROXY_SYMBOLS = ["US.NDX", "US.SPX", "US.DJI", "US.VIX"]
ALL_SYMBOLS = ETF_SYMBOLS + PROXY_SYMBOLS
SEGMENTS = {"2020_2022": ("2020-01-01", "2022-12-31"), "2023_2024": ("2023-01-01", "2024-12-31"), "2025_2026": ("2025-01-01", DEFAULT_END)}
STATIC_STRATEGIES = {
    "QQQ_USMV_IEF_SHV": {"US.QQQ": .35, "US.USMV": .25, "US.IEF": .20, "US.SHV": .20},
    "QQQ_TAIL_IEF_SHV": {"US.QQQ": .35, "US.TAIL": .20, "US.IEF": .25, "US.SHV": .20},
    "QQQ_DBMF_BTAL_SHV": {"US.QQQ": .35, "US.DBMF": .25, "US.BTAL": .20, "US.SHV": .20},
}
PROXY_PLAN = {
    "US.QQQ": {"pre_inception_proxy": "US.NDX", "reason": "Nasdaq-100 index proxy; not QQQ ETF performance"},
    "US.SPY": {"pre_inception_proxy": "US.SPX", "reason": "S&P 500 index proxy; not SPY ETF performance"},
    "US.TLT": {"pre_inception_proxy": None, "reason": "No acceptable bond proxy established in OpenD-only run"},
    "US.IEF": {"pre_inception_proxy": None, "reason": "No acceptable bond proxy established in OpenD-only run"},
    "US.SHV": {"pre_inception_proxy": None, "reason": "No acceptable cash proxy established in OpenD-only run"},
    "US.GLDM": {"pre_inception_proxy": None, "reason": "Gold spot/total-return proxy requires separate verified series"},
    "US.DBMF": {"pre_inception_proxy": None, "reason": "No ETF-equivalent managed-futures history verified"},
    "US.BTAL": {"pre_inception_proxy": None, "reason": "No ETF-equivalent long history verified"},
    "US.TAIL": {"pre_inception_proxy": "US.VIX", "reason": "VIX is not a TAIL return proxy; research-only stress context"},
}


def dynamic_tail_weights(index: pd.DatetimeIndex, qqq: pd.Series) -> pd.DataFrame:
    """Fixed rule: yesterday's 60d drawdown or 200d trend selects next-day weights."""
    price = qqq.reindex(index).ffill()
    peak = price.rolling(60, min_periods=60).max()
    drawdown = price / peak - 1.0
    ma200 = price.rolling(200, min_periods=200).mean()
    defensive = (drawdown <= -0.08) | (price < ma200)
    regime = defensive.shift(1).fillna(False).astype(bool)
    normal = {"US.QQQ": .50, "US.TAIL": .10, "US.IEF": .20, "US.SHV": .20}
    hedge = {"US.QQQ": .15, "US.TAIL": .35, "US.IEF": .25, "US.SHV": .25}
    weights = pd.DataFrame(0.0, index=index, columns=list(normal))
    weights.loc[~regime, list(normal)] = list(normal.values())
    weights.loc[regime, list(hedge)] = list(hedge.values())
    return weights


def metrics(returns: pd.Series, qqq: pd.Series, turnover: pd.Series, strategy: str, year: int | str) -> dict:
    frame = pd.DataFrame({"p": returns, "q": qqq, "t": turnover}).dropna(subset=["p"])
    return {
        "strategy": strategy, "year": year, "start": str(frame.index.min().date()), "end": str(frame.index.max().date()), "n_days": len(frame),
        "return": float((1 + frame.p).prod() - 1), "max_drawdown": max_drawdown(frame.p), "turnover": float(frame.t.sum()),
        "qqq_up_day_follow_rate": float((frame.loc[frame.q > 0, "p"] > 0).mean()) if (frame.q > 0).any() else np.nan,
        "qqq_down_day_up_rate": float((frame.loc[frame.q < 0, "p"] > 0).mean()) if (frame.q < 0).any() else np.nan,
        **{f"qqq_down_{n}pct_up_rate": float((frame.loc[frame.q <= -n / 100, "p"] > 0).mean()) if (frame.q <= -n / 100).any() else np.nan for n in (1, 2, 3)},
        **{f"qqq_down_{n}pct_mean": float(frame.loc[frame.q <= -n / 100, "p"].mean()) if (frame.q <= -n / 100).any() else np.nan for n in (1, 2, 3)},
    }


def run(raw: dict[str, pd.DataFrame], output_dir: Path, end: str, errors: dict[str, str]) -> dict[str, str]:
    available = {s: raw[s] for s in ALL_SYMBOLS if s in raw}
    qqq = raw["US.QQQ"].set_index("date")["close"]
    definitions = dict(STATIC_STRATEGIES)
    definitions["DYNAMIC_TAIL_QQQ_IEF_SHV"] = None
    rows = []
    for name, definition in definitions.items():
        symbols = ["US.QQQ", "US.TAIL", "US.IEF", "US.SHV"] if definition is None else list(definition)
        if any(s not in raw for s in symbols):
            continue
        prices = strategy_prices(raw, symbols)
        weights = dynamic_tail_weights(prices.index, qqq) if definition is None else pd.DataFrame(definition, index=prices.index)
        returns, turnover = build_returns(prices, weights, 5, 5)
        qret = qqq.reindex(prices.index).pct_change()
        for segment, (start, stop) in SEGMENTS.items():
            part = returns.loc[start:stop]
            if part.empty: continue
            rows.append(metrics(part, qret.reindex(part.index), turnover.reindex(part.index), name, segment))
            for year, group in part.groupby(part.index.year):
                rows.append(metrics(group, qret.reindex(group.index), turnover.reindex(group.index), name, int(year)))
    qret = qqq.pct_change()
    zero = pd.Series(0.0, index=qret.index)
    for segment, (start, stop) in SEGMENTS.items():
        part = qret.loc[start:stop]
        rows.append(metrics(part, part, zero.reindex(part.index), "QQQ_BENCHMARK", segment))
    coverage = []
    for symbol in ALL_SYMBOLS:
        frame = raw.get(symbol)
        coverage.append({"symbol": symbol, "status": "OK" if frame is not None else "ERROR_OR_EMPTY", "official_inception_date": "UNKNOWN", "first_readable_date": str(frame.date.min().date()) if frame is not None else None, "last_readable_date": str(frame.date.max().date()) if frame is not None else None, "rows": len(frame) if frame is not None else 0, "error": errors.get(symbol), "proxy_plan": PROXY_PLAN.get(symbol)})
    output_dir.mkdir(parents=True, exist_ok=True)
    prefix = "stock_razor_dual_market_strategy_v05_2026-10-18"
    paths = {k: output_dir / f"{prefix}_{v}" for k, v in {"metrics": "metrics.csv", "coverage": "coverage.csv", "metadata": "metadata.json", "report": "report.md"}.items()}
    pd.DataFrame(rows).to_csv(paths["metrics"], index=False, encoding="utf-8-sig")
    pd.DataFrame(coverage).to_csv(paths["coverage"], index=False, encoding="utf-8-sig")
    meta = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "source": "local OpenD only", "endpoint": "127.0.0.1:11111", "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ", "end": end}, "cost": {"fee_bps": 5, "slippage_bps": 5}, "next_day_effective": True, "strategies": definitions, "coverage": coverage, "provider_finality": "UNKNOWN", "timezone_exchange_calendar": "UNKNOWN", "oos_status": "NOT_VERIFIED", "trade_execution": "NO", "radar_admission": "BLOCKED"}
    meta["sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (paths["metrics"], paths["coverage"])}
    paths["metadata"].write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    report = ["# STOCK RAZOR Dual-Market Strategy V0.5", "", f"- 正式行情证据：OpenD `127.0.0.1:11111`，`K_DAY/RTH/QFQ`，截止 `{end}`。", "- 静态候选和动态 TAIL 规则在读取数据前固定；调仓权重下一交易日生效；成本固定为 5bp 费用 + 5bp 滑点。", "- 动态 TAIL：过去 60 个已读交易日回撤 <= 8% 或价格低于 200 日均线时，下一交易日提高 TAIL/IEF/SHV 权重。", "- `provider_finality=UNKNOWN`、独立交易日历/时区 `UNKNOWN`、`OOS=NOT_VERIFIED`、`TRADE_EXECUTION=NO`、`RADAR_ADMISSION=BLOCKED`。", "", "## 2000—2026 覆盖方案", "", "coverage.csv` 同时保留 `official_inception_date=UNKNOWN` 和真实 OpenD 首个可读日期；本轮没有把两者混为一谈。ETF 上市前不回填。NDX/SPX 本轮无可读数据，不能作为本轮正式 proxy 证据；VIX 只能作为 TAIL 压力背景，不能作为 TAIL 收益 proxy。债券、现金、黄金、DBMF、BTAL、TAIL 的上市前历史没有在本轮构造。", "", "## 文件", ""]
    report.extend(f"- `{p.name}`" for p in paths.values())
    paths["report"].write_text("\n".join(report) + "\n", encoding="utf-8")
    return {k: str(v) for k, v in paths.items()}


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--end", default=DEFAULT_END); parser.add_argument("--output-dir", type=Path, required=True); args = parser.parse_args()
    from futu import OpenQuoteContext
    ctx = OpenQuoteContext(host="127.0.0.1", port=11111); raw, errors = {}, {}
    try:
        for symbol in ALL_SYMBOLS:
            frame, status = fetch_history(ctx, symbol, args.end)
            if frame is None: errors[symbol] = status
            else: raw[symbol] = frame
    finally: ctx.close()
    if "US.QQQ" not in raw: raise RuntimeError(f"required QQQ unavailable; errors={errors}")
    print(json.dumps(run(raw, args.output_dir, args.end, errors), ensure_ascii=False, indent=2))


if __name__ == "__main__": main()

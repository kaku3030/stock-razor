"""Round11 research-only coverage, frozen-regime and portfolio-MDD audit.

This consumes existing local Futu/OpenD CSV captures.  It does not download,
interpolate, or substitute missing data.  The Round10 signal engine remains the
only executable proxy path; this module adds coverage evidence and recomputes
portfolio equity on one timestamp axis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import pandas as pd

from tools.research.round10_radar_replay import (
    COST_BPS,
    RISK_BUDGET,
    SECTOR,
    SYMBOLS as ROUND10_SYMBOLS,
    _indicators,
    _read,
    _risk_replay,
    _signals,
)

SYMBOLS = ("NVDA", "AMD", "TSLA", "AAPL", "COHR", "QQQ", "TSM", "AVGO", "MU", "INTC", "MSFT", "GOOGL", "META", "PLTR", "HOOD", "SPY", "IWM", "SMH", "XLK")
TIMEFRAMES = ("D1", "1H", "15m", "5m", "1m")
PROTOCOLS = ("A_D1_1H", "B_D1_1H_15m", "C_D1_1H_15m_5m", "D_D1_1H_15m_5m_1m", "E_D1_1H_5m_1m_AUDIT")


def _path(capture: Path, symbol: str, timeframe: str) -> Path:
    return capture / f"US_{symbol}_{timeframe}_qfq_rth_20190101_20261016.csv"


def _coverage(capture: Path) -> pd.DataFrame:
    rows = []
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            path = _path(capture, symbol, timeframe)
            row = {"symbol": symbol, "timeframe": timeframe, "path": str(path), "status": "NOT_VERIFIED", "rows": 0, "first": None, "last": None, "sha256": None, "source_boundary": "authorized local Futu/OpenD capture"}
            if path.exists():
                frame = _read(path)
                row.update(status="AVAILABLE", rows=len(frame), first=frame.time_key.min().isoformat(), last=frame.time_key.max().isoformat(), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            rows.append(row)
    return pd.DataFrame(rows)


def _regime(d1: pd.DataFrame, hourly: pd.DataFrame, at: pd.Timestamp) -> str:
    """Frozen before replay: prior completed D1 plus prior completed 1H only."""
    d = d1[d1.time_key < at].iloc[-1:] if not d1[d1.time_key < at].empty else d1.iloc[0:0]
    h = hourly[hourly.time_key < at].iloc[-1:] if not hourly[hourly.time_key < at].empty else hourly.iloc[0:0]
    if d.empty or h.empty:
        return "UNKNOWN"
    d = d.iloc[0]; h = h.iloc[0]
    values = [d.get("ema20"), d.get("ema50"), d.get("ema20_slope"), h.get("ema20"), h.get("ema50"), h.get("ema20_slope")]
    if any(pd.isna(x) for x in values):
        return "UNKNOWN"
    if d.ema20 > d.ema50 and d.ema20_slope > 0 and h.ema20 > h.ema50 and h.ema20_slope > 0:
        return "TREND_UP"
    if d.ema20 < d.ema50 and d.ema20_slope < 0 and h.ema20 < h.ema50 and h.ema20_slope < 0:
        return "TREND_DOWN"
    if abs(float(d.ema20_slope)) <= 0.001 and abs(float(h.ema20_slope)) <= 0.001:
        return "RANGE"
    return "TRANSITION"


def _with_regime(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["ema20"] = out.close.ewm(span=20, adjust=False, min_periods=20).mean()
    out["ema50"] = out.close.ewm(span=50, adjust=False, min_periods=50).mean()
    out["ema20_slope"] = out.ema20.pct_change(5)
    return out


def _price_at_or_before(frame: pd.DataFrame, timestamp: pd.Timestamp) -> float:
    prices = frame.loc[frame.time_key <= timestamp, "close"]
    if prices.empty:
        raise ValueError(f"missing price at or before {timestamp}")
    value = float(prices.iloc[-1])
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"non-finite or non-positive price at {timestamp}")
    return value


def _portfolio_curve(trades: pd.DataFrame, prepared: dict[str, dict[str, pd.DataFrame]]) -> pd.DataFrame:
    """Build one protocol's cash plus marked holdings ledger."""
    columns = ["time_key", "cash", "holdings_market_value", "unrealized_pnl", "total_equity", "drawdown"]
    if trades.empty:
        return pd.DataFrame(columns=columns)
    timestamps = pd.DatetimeIndex(sorted({t for symbol in prepared for t in prepared[symbol]["5m"].time_key}))
    if not timestamps.is_unique or not timestamps.is_monotonic_increasing:
        raise ValueError("5m timeline must be sorted and unique")
    cash_changes = pd.Series(0.0, index=timestamps, dtype=float)
    holdings_value = pd.Series(0.0, index=timestamps, dtype=float)
    open_cost = pd.Series(0.0, index=timestamps, dtype=float)
    close_by_symbol = {symbol: prepared[symbol]["5m"].set_index("time_key").close.reindex(timestamps).ffill() for symbol in prepared}
    for _, trade in trades.iterrows():
        symbol = str(trade.symbol)
        entry_time = pd.Timestamp(trade.entry_time)
        exit_time = pd.Timestamp(trade.exit_time)
        entry_price = float(trade.entry_price)
        exit_price = float(trade.exit_price)
        units = float(trade.units)
        if not all(math.isfinite(value) for value in (entry_price, exit_price, units)) or entry_price <= 0 or exit_price <= 0 or units <= 0:
            raise ValueError("trade prices and units must be finite and positive")
        if entry_time not in timestamps or exit_time not in timestamps or exit_time < entry_time:
            raise ValueError("trade timestamps must be on the 5m timeline")
        if symbol not in close_by_symbol:
            raise ValueError(f"missing 5m prices for {symbol}")
        cash_changes.loc[entry_time] -= entry_price * units * (1 + COST_BPS / 10000)
        cash_changes.loc[exit_time] += exit_price * units * (1 - COST_BPS / 10000)
        mask = (timestamps >= entry_time) & (timestamps < exit_time)
        prices = close_by_symbol[symbol].loc[mask]
        if prices.isna().any() or (~prices.map(lambda value: math.isfinite(float(value)))).any() or (prices <= 0).any():
            raise ValueError(f"missing or invalid active price for {symbol}")
        holdings_value.loc[mask] += units * prices
        open_cost.loc[mask] += units * entry_price
    cash = 100000.0 + cash_changes.cumsum()
    if (cash < -1e-8).any():
        raise ValueError("cash became negative")
    out = pd.DataFrame({"time_key": timestamps, "cash": cash.to_numpy(), "holdings_market_value": holdings_value.to_numpy()})
    out["unrealized_pnl"] = out.holdings_market_value - open_cost.to_numpy()
    out["total_equity"] = out.cash + out.holdings_market_value
    out["drawdown"] = out.total_equity.cummax() - out.total_equity
    out["running_peak"] = out.total_equity.cummax()
    trough_index = int(out.drawdown.to_numpy().argmax())
    peak_index = int(out.total_equity.iloc[:trough_index + 1].to_numpy().argmax())
    out["peak_time"] = out.iloc[peak_index]["time_key"]
    out["trough_time"] = out.iloc[trough_index]["time_key"]
    out["accounting_residual"] = out.total_equity - out.cash - out.holdings_market_value
    return out


def _accept_protocol_trades(signal_df: pd.DataFrame, protocol: str, prepared: dict[str, dict[str, pd.DataFrame]]) -> pd.DataFrame:
    """Accept one protocol with its own cash, positions and equity."""
    accepted: list[dict] = []
    active: list[dict] = []
    cash = 100000.0
    for _, row in signal_df[signal_df.protocol == protocol].sort_values(["signal_time", "symbol"]).iterrows():
        ts = pd.Timestamp(row.signal_time)
        still_active = []
        for position in active:
            if position["end"] <= ts:
                cash += position["exit_proceeds"]
            else:
                still_active.append(position)
        active = still_active
        sector_counts: dict[str, int] = {}
        for position in active:
            sector_counts[position["sector"]] = sector_counts.get(position["sector"], 0) + 1
        if len(active) >= 3 or sector_counts.get(row.sector, 0) >= 2:
            continue
        equity = cash + sum(position["units"] * _price_at_or_before(prepared[position["symbol"]]["5m"], ts) for position in active)
        audit = _risk_replay(row.to_dict(), prepared[row.symbol]["5m"], prepared[row.symbol][row.execution_timeframe], equity)
        if audit.get("net_pnl") is None:
            continue
        entry_cost = float(audit["entry_price"]) * float(audit["units"]) * (1 + COST_BPS / 10000)
        if not math.isfinite(entry_cost) or entry_cost <= 0 or entry_cost > cash + 1e-8:
            continue
        exit_proceeds = float(audit["exit_price"]) * float(audit["units"]) * (1 - COST_BPS / 10000)
        cash -= entry_cost
        accepted.append({**row.to_dict(), **audit, "portfolio_equity_before": equity, "cash_after_entry": cash})
        active.append({"end": pd.Timestamp(audit["exit_time"]), "sector": row.sector, "symbol": row.symbol, "units": float(audit["units"]), "exit_proceeds": exit_proceeds})
    return pd.DataFrame(accepted)


def run(capture: Path, out: Path) -> dict:
    started = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    coverage = _coverage(capture)
    coverage.to_csv(out / "round11_coverage_audit.csv", index=False)
    coverage.to_csv(out / "round12_coverage_audit.csv", index=False)
    available = [s for s in ROUND10_SYMBOLS if all(_path(capture, s, tf).exists() for tf in ("D1", "1H", "15m", "5m"))]
    prepared = {}
    source_manifest = []
    for symbol in available:
        frames = {tf: _with_regime(_indicators(_read(_path(capture, symbol, tf)))) for tf in ("D1", "1H", "15m", "5m")}
        prepared[symbol] = frames
        source_manifest.extend({"symbol": symbol, "timeframe": tf, "path": str(_path(capture, symbol, tf)), "sha256": hashlib.sha256(_path(capture, symbol, tf).read_bytes()).hexdigest(), "rows": len(frames[tf])} for tf in frames)
    signals = []
    for symbol, frames in prepared.items():
        hashes = {tf: hashlib.sha256(_path(capture, symbol, tf).read_bytes()).hexdigest() for tf in ("D1", "1H", "15m", "5m")}
        for signal in _signals(symbol, frames, hashes):
            signal["market_regime"] = _regime(frames["D1"], frames["1H"], pd.Timestamp(signal["signal_time"]))
            signals.append(signal)
    signal_df = pd.DataFrame(signals)
    protocol_trades = {protocol: _accept_protocol_trades(signal_df, protocol, prepared) for protocol in ("II", "III")}
    trades = pd.concat(protocol_trades.values(), ignore_index=True) if any(not frame.empty for frame in protocol_trades.values()) else pd.DataFrame()
    if not trades.empty:
        trades.to_csv(out / "round11_trade_ledger.csv", index=False)
        trades.to_csv(out / "round12_trade_ledger.csv", index=False)
        trades["entry_time"] = pd.to_datetime(trades.entry_time)
        trades["exit_time"] = pd.to_datetime(trades.exit_time)
    curves = []
    metrics = []
    for protocol, group in protocol_trades.items():
        pnl = pd.to_numeric(group.net_pnl, errors="coerce").dropna(); wins = pnl[pnl > 0]; losses = pnl[pnl < 0]
        curve = _portfolio_curve(group, prepared)
        curve.insert(1, "protocol", protocol)
        curves.append(curve)
        trough = curve.iloc[int(curve.drawdown.argmax())] if not curve.empty else None
        metrics.append({"protocol": protocol, "signals": int((signal_df.protocol == protocol).sum()), "trades": len(group), "net_pnl": float(pnl.sum()), "profit_factor": float(wins.sum() / abs(losses.sum())) if not losses.empty else None, "event_mdd": float((pnl.cumsum().cummax() - pnl.cumsum()).max()) if not pnl.empty else 0.0, "portfolio_total_equity_mdd": float(curve.drawdown.max()) if not curve.empty else 0.0, "minimum_total_equity": float(curve.total_equity.min()) if not curve.empty else None, "maximum_total_equity": float(curve.total_equity.max()) if not curve.empty else None, "mdd_peak_time": str(trough.peak_time) if trough is not None else None, "mdd_trough_time": str(trough.trough_time) if trough is not None else None, "cash_minimum": float(curve.cash.min()) if not curve.empty else None, "accounting_residual_max_abs": float(curve.accounting_residual.abs().max()) if not curve.empty else None, "win_rate": float((pnl > 0).mean()) if not pnl.empty else None})
    curve = pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()
    curve.to_csv(out / "round11_portfolio_equity_curve.csv", index=False)
    curve.to_csv(out / "round12_portfolio_equity_curve.csv", index=False)
    pd.DataFrame(metrics).to_csv(out / "round11_metrics.csv", index=False)
    pd.DataFrame(metrics).to_csv(out / "round12_metrics.csv", index=False)
    regime = signal_df.groupby(["protocol", "market_regime"]).size().reset_index(name="signals") if not signal_df.empty else pd.DataFrame(columns=["protocol", "market_regime", "signals"])
    regime.to_csv(out / "round11_regime_statistics.csv", index=False)
    regime.to_csv(out / "round12_regime_statistics.csv", index=False)
    protocol_rows = [{"protocol": p, "status": "NOT_VERIFIED" if p.startswith("D") else ("EXECUTED_RESEARCH_PROXY" if available else "NOT_VERIFIED"), "reason": "1m capture missing" if p.startswith("D") else "Round10 proxy path with frozen regime label"} for p in PROTOCOLS]
    pd.DataFrame(protocol_rows).to_csv(out / "round11_protocol_matrix.csv", index=False)
    pd.DataFrame(protocol_rows).to_csv(out / "round12_protocol_matrix.csv", index=False)
    manifest_paths = [out / "round12_portfolio_equity_curve.csv", out / "round12_metrics.csv", out / "round12_trade_ledger.csv", out / "round12_coverage_audit.csv", out / "round12_regime_statistics.csv", out / "round12_protocol_matrix.csv"]
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in manifest_paths if path.exists()}
    residual = float(curve.accounting_residual.abs().max()) if not curve.empty else None
    status = {"schema_version": "stock-razor-round12-radar-research-v0.1", "status": "RESEARCH_ONLY", "symbols_target": len(SYMBOLS), "symbols_with_complete_5m_path": available, "symbols_not_verified": [s for s in SYMBOLS if s not in available], "source_manifest": source_manifest, "regime_freeze": {"inputs": "prior completed D1 and prior completed 1H only", "labels": ["TREND_UP", "TREND_DOWN", "RANGE", "TRANSITION", "UNKNOWN"], "thresholds": "EMA20/EMA50 ordering and 5-bar EMA20 slope; abs slope <= 0.001 for RANGE"}, "data_quality": {"provider": "Futu/OpenD only", "timezone": "UNKNOWN", "bar_closure": "UNKNOWN", "provider_finality": "UNKNOWN", "a_share_tickflow": "NOT_VERIFIED"}, "accounting": {"initial_equity": 100000.0, "protocols_are_independent": True, "formula": "total_equity=cash+holdings_market_value", "mdd": "running_peak-total_equity", "missing_prices": "FAIL_CLOSED", "cash_constraint": "cash >= 0", "accounting_residual_max_abs": residual}, "mdd_method": "per-protocol single timestamp axis cash + holdings market value; realized exit proceeds are not re-added to holdings; gap and same-bar stop conservative in inherited 5m audit", "protocol_matrix": protocol_rows, "artifact_sha256": hashes, "elapsed_seconds": time.perf_counter() - started, "safety": {"RADAR_ADMISSION": "BLOCKED", "PAPER_AUTO_READY": "NO", "LIVE_TRADE": "NO", "TRADE_EXECUTION": "NO"}}
    (out / "round11_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "round12_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    report_lines = ["# STOCK RAZOR Round12 P0 资金/总权益修复", "", "状态：`RESEARCH_ONLY`；`RADAR_ADMISSION=BLOCKED`；`PAPER_AUTO_READY=NO`；`LIVE_TRADE=NO`；`TRADE_EXECUTION=NO`。", "", "## 会计修复", "", "- II 与 III 分别拥有独立 cash、active positions 和 marked holdings；不再共享账本。", "- `total_equity = cash + holdings_market_value`；已实现退出回款只进入 cash，未实现盈亏只来自持仓市值。", "- MDD 按每协议自己的 running peak 到 trough 计算，报告峰值/谷值时间。", "- 现金为负、缺失/非 finite/非正价格、非时间轴交易时间均 fail-closed。", "", "## 结果", ""]
    for row in metrics:
        report_lines.append(f"- `{row['protocol']}`：trades={row['trades']}，net PnL=${row['net_pnl']:.2f}，PF={row['profit_factor']!s}，MDD=${row['portfolio_total_equity_mdd']:.2f}，min equity=${row['minimum_total_equity']:.2f}，max equity=${row['maximum_total_equity']:.2f}，MDD区间={row['mdd_peak_time']} → {row['mdd_trough_time']}，cash_min=${row['cash_minimum']:.2f}，residual_max=${row['accounting_residual_max_abs']:.12f}。")
    report_lines += ["", "## 未验证与边界", "", "1m 与 13 只标的仍为 `NOT_VERIFIED`；QFQ 股息/拆分语义、provider finality、时区/DST、bar closure 仍 `UNKNOWN`。本轮不获取 1m、不生成新信号、不调用收费源、不提交/合并/部署/下单。", "", f"耗时：{status['elapsed_seconds']:.3f}s", ""]
    (out / "round12_report.md").write_text("\n".join(report_lines), encoding="utf-8")
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.capture, args.out), ensure_ascii=False, indent=2, default=str))

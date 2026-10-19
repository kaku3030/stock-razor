"""Round13 research-only OOS, walk-forward and attribution replay.

This reuses the frozen Round12 signal and accounting path.  No parameters are
fit on the test windows.  15m is a closed-bar signal filter; 5m is only an
offline execution/stop audit.  Missing 1m and non-authorized symbols remain
NOT_VERIFIED.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import pandas as pd

from tools.research.round10_radar_replay import _indicators, _read, _signals
from tools.research.round11_radar_research import (
    ROUND10_SYMBOLS,
    SYMBOLS,
    _accept_protocol_trades,
    _portfolio_curve,
    _regime,
    _with_regime,
)

COSTS_BPS = (5.0, 10.0, 20.0)
OOS_START = pd.Timestamp("2024-01-01")
WF_WINDOWS = (("2021", "2022-01-01", "2022-12-31"), ("2022", "2023-01-01", "2023-12-31"), ("2023", "2024-01-01", "2024-12-31"), ("2024", "2025-01-01", "2025-12-31"))


def _path(capture: Path, symbol: str, tf: str) -> Path:
    return capture / f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv"


def _metric(group: pd.DataFrame, prepared: dict) -> dict:
    pnl = pd.to_numeric(group.net_pnl, errors="coerce").dropna()
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    curve = _portfolio_curve(group, prepared)
    return {
        "trades": int(len(group)), "net_pnl": float(pnl.sum()),
        "profit_factor": float(wins.sum() / abs(losses.sum())) if not losses.empty else None,
        "total_equity_mdd": float(curve.drawdown.max()) if not curve.empty else 0.0,
        "min_total_equity": float(curve.total_equity.min()) if not curve.empty else None,
        "buy_hold": None, "cost_bps_per_side": None,
    }


def _buy_hold(prepared: dict, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    values = []
    for symbol, frames in prepared.items():
        d1 = frames["D1"]
        rows = d1[(d1.time_key >= start) & (d1.time_key <= end)]
        if len(rows) >= 2:
            values.append(float(rows.close.iloc[-1] / rows.close.iloc[0] - 1.0))
    return float(sum(values) / len(values)) if values else None


def _slice_metrics(signal_df: pd.DataFrame, prepared: dict, key: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for protocol in ("II", "III"):
        window_signals = signal_df[(pd.to_datetime(signal_df.signal_time) >= start) & (pd.to_datetime(signal_df.signal_time) <= end)]
        group = _accept_protocol_trades(window_signals, protocol, prepared)
        row = _metric(group, prepared)
        row.update({"protocol": protocol, key: str(start.date()), "buy_hold": _buy_hold(prepared, start, end)})
        rows.append(row)
    return pd.DataFrame(rows)


def _p0_audit(trades: pd.DataFrame, curves: pd.DataFrame) -> dict:
    checks = {"independent_protocols": set(curves.protocol) == {"II", "III"}, "ordered_trades": True, "valid_prices": True, "valid_stops": True, "equity_identity": True, "cash_nonnegative": True, "drawdown_nonnegative": True}
    for protocol, group in trades.groupby("protocol"):
        times = pd.to_datetime(group.signal_time)
        checks["ordered_trades"] &= times.is_monotonic_increasing
        checks["valid_prices"] &= group.entry_price.map(lambda x: float(x) > 0).all() and group.exit_price.map(lambda x: float(x) > 0).all()
        checks["valid_stops"] &= (pd.to_numeric(group.stop_price, errors="coerce") > 0).all() & (pd.to_numeric(group.stop_price, errors="coerce") < pd.to_numeric(group.entry_price, errors="coerce")).all()
        curve = curves[curves.protocol == protocol]
        checks["equity_identity"] &= (curve.total_equity - curve.cash - curve.holdings_market_value).abs().max() <= 1e-7
        checks["cash_nonnegative"] &= (curve.cash >= -1e-7).all()
        checks["drawdown_nonnegative"] &= (curve.drawdown >= -1e-7).all()
    return {"checks": checks, "pass": all(checks.values()), "max_residual": float(curves.accounting_residual.abs().max()) if not curves.empty else None}


def run(capture: Path, out: Path) -> dict:
    started = time.perf_counter(); out.mkdir(parents=True, exist_ok=True)
    available = [s for s in ROUND10_SYMBOLS if all(_path(capture, s, tf).exists() for tf in ("D1", "1H", "15m", "5m"))]
    prepared = {}; manifest = []
    for symbol in available:
        frames = {tf: _with_regime(_indicators(_read(_path(capture, symbol, tf)))) for tf in ("D1", "1H", "15m", "5m")}
        prepared[symbol] = frames
        manifest += [{"symbol": symbol, "timeframe": tf, "rows": len(frames[tf]), "sha256": hashlib.sha256(_path(capture, symbol, tf).read_bytes()).hexdigest()} for tf in frames]
    signals = []
    for symbol, frames in prepared.items():
        hashes = {tf: hashlib.sha256(_path(capture, symbol, tf).read_bytes()).hexdigest() for tf in ("D1", "1H", "15m", "5m")}
        for signal in _signals(symbol, frames, hashes):
            signal["market_regime"] = _regime(frames["D1"], frames["1H"], pd.Timestamp(signal["signal_time"]))
            signals.append(signal)
    signal_df = pd.DataFrame(signals)
    protocols = {p: _accept_protocol_trades(signal_df, p, prepared) for p in ("II", "III")}
    trades = pd.concat(protocols.values(), ignore_index=True)
    curves = pd.concat([_portfolio_curve(frame, prepared).assign(protocol=p) for p, frame in protocols.items()], ignore_index=True)
    trades.to_csv(out / "round13_trade_ledger.csv", index=False); signal_df.to_csv(out / "round13_signal_ledger.csv", index=False); curves.to_csv(out / "round13_portfolio_equity_curve.csv", index=False)
    p0 = _p0_audit(trades, curves); pd.DataFrame([p0["checks"]]).to_csv(out / "round13_p0_audit.csv", index=False)
    oos = _slice_metrics(signal_df, prepared, "window", OOS_START, pd.Timestamp("2026-10-16")); oos.to_csv(out / "round13_oos_metrics.csv", index=False)
    wf = pd.concat([_slice_metrics(signal_df, prepared, "test_year", pd.Timestamp(start), pd.Timestamp(end)) for _, start, end in WF_WINDOWS], ignore_index=True); wf.to_csv(out / "round13_walk_forward_metrics.csv", index=False)
    regime = trades.groupby(["protocol", "market_regime"], dropna=False).agg(trades=("protocol", "size"), net_pnl=("net_pnl", "sum")).reset_index(); regime.to_csv(out / "round13_regime_metrics.csv", index=False)
    ablation = pd.DataFrame([{"protocol": "III", "stage": "D1+1H", "role": "high_timeframe_candidate", "status": "EXECUTED_RESEARCH_PROXY"}, {"protocol": "II", "stage": "D1+1H+15m", "role": "15m_closed_filter_and_timing", "status": "EXECUTED_RESEARCH_PROXY"}, {"protocol": "II", "stage": "5m", "role": "offline_execution_stop_audit", "status": "EXECUTED_RESEARCH_PROXY"}, {"protocol": "D", "stage": "1m", "role": "offline execution audit", "status": "NOT_VERIFIED"}]); ablation.to_csv(out / "round13_ablation_metrics.csv", index=False)
    pressure = []
    for cost in COSTS_BPS:
        for protocol, group in protocols.items():
            gross = pd.to_numeric(group.gross_pnl, errors="coerce").sum()
            notional = (pd.to_numeric(group.entry_price, errors="coerce") * pd.to_numeric(group.units, errors="coerce") + pd.to_numeric(group.exit_price, errors="coerce") * pd.to_numeric(group.units, errors="coerce")).sum()
            row = _metric(group, prepared); row.update({"protocol": protocol, "cost_bps_per_side": cost, "net_pnl": float(gross - notional * cost / 10000), "note": "gross trade prices minus entry and exit costs"}); pressure.append(row)
    pd.DataFrame(pressure).to_csv(out / "round13_cost_pressure.csv", index=False)
    winner_rows = []
    for protocol, group in protocols.items():
        if group.empty:
            continue
        winner = group.net_pnl.astype(float).idxmax(); kept = group.drop(index=winner)
        row = _metric(kept, prepared); row.update({"protocol": protocol, "excluded_trade_index": int(winner), "excluded_net_pnl": float(group.loc[winner, "net_pnl"])})
        winner_rows.append(row)
    pd.DataFrame(winner_rows).to_csv(out / "round13_winner_exclusion.csv", index=False)
    annual = trades.assign(year=pd.to_datetime(trades.signal_time).dt.year).groupby(["protocol", "year"], as_index=False).agg(trades=("protocol", "size"), net_pnl=("net_pnl", "sum")); annual.to_csv(out / "round13_annual_metrics.csv", index=False)
    symbol = trades.groupby(["protocol", "symbol"], as_index=False).agg(trades=("protocol", "size"), net_pnl=("net_pnl", "sum")); symbol.to_csv(out / "round13_symbol_metrics.csv", index=False)
    files = [p for p in out.glob("round13_*") if p.is_file() and p.name != "round13_status.json" and p.name != "round13_report.md"]
    status = {"schema_version": "stock-razor-round13-radar-research-v0.1", "status": "RESEARCH_ONLY", "base_commit": "e43ad28dec3d264560cd3cfbebb069ecb02f35a8", "available_symbols": available, "not_verified_symbols": [s for s in SYMBOLS if s not in available], "one_minute": "NOT_VERIFIED", "p0": p0, "source_manifest": manifest, "artifact_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, "elapsed_seconds": time.perf_counter() - started, "safety": {"RADAR_ADMISSION": "BLOCKED", "PAPER_AUTO_READY": "NO", "LIVE_TRADE": "NO", "TRADE_EXECUTION": "NO"}}
    (out / "round13_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    report = ["# STOCK RAZOR Round13 工程回测", "", "状态：`RESEARCH_ONLY`；`RADAR_ADMISSION=BLOCKED`；`PAPER_AUTO_READY=NO`；`LIVE_TRADE=NO`；`TRADE_EXECUTION=NO`。", "", f"P0 独立账本复核：{'PASS' if p0['pass'] else 'BLOCKED'}；最大守恒残差={p0['max_residual']}", "", "OOS、walk-forward、regime、15m/5m 消融、成本压力、剔除最大赢家、年度与标的贡献见 CSV。15m 仅作事前闭合过滤/择时，5m 仅作离线执行止损审计；1m 与 13 只标的为 `NOT_VERIFIED`。", "", f"耗时：{status['elapsed_seconds']:.3f}s"]
    (out / "round13_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--capture", type=Path, required=True); parser.add_argument("--out", type=Path, required=True); args = parser.parse_args(); print(json.dumps(run(args.capture, args.out), ensure_ascii=False, indent=2, default=str))

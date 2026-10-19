"""Round10 research-only D1/1H/15m signal and portfolio replay.

The production Radar rule is not frozen.  II and III are explicit research
proxies.  III is intentionally generated only from completed D1 and 1H bars;
15m is never read by that signal path.  5m is used only for offline risk exit
auditing after an entry has already been created.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

SYMBOLS = ("AAPL", "AMD", "COHR", "NVDA", "QQQ", "TSLA")
SECTOR = {"AAPL": "TECH", "AMD": "SEMIS", "COHR": "SEMIS", "NVDA": "SEMIS", "QQQ": "ETF", "TSLA": "AUTO"}
COST_BPS = 5.0
RISK_BUDGET = 0.0025


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["time_key"] = pd.to_datetime(frame["time_key"], errors="raise")
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    return frame.sort_values("time_key", kind="mergesort").drop_duplicates("time_key").reset_index(drop=True)


def _indicators(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["ma20"] = out.close.rolling(20, min_periods=20).mean()
    out["ma50"] = out.close.rolling(50, min_periods=50).mean()
    out["atr20"] = (out.high - out.low).rolling(20, min_periods=20).mean()
    out["prior_high20"] = out.high.rolling(20, min_periods=20).max().shift(1)
    out["prior_low20"] = out.low.rolling(20, min_periods=20).min().shift(1)
    out["volume_ma20"] = out.volume.rolling(20, min_periods=20).mean()
    return out


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _daily_context(d1: pd.DataFrame, at: pd.Timestamp) -> pd.Series | None:
    rows = d1[d1.time_key < at]
    if rows.empty:
        return None
    row = rows.iloc[-1]
    return row if pd.notna(row.ma20) and pd.notna(row.ma50) else None


def _signals(symbol: str, frames: dict[str, pd.DataFrame], hashes: dict[str, str]) -> list[dict]:
    d1, hourly, m15 = frames["D1"], frames["1H"], frames["15m"]
    rows: list[dict] = []
    # II: D1+1H filters, 15m closed-bar breakout and next 15m open.
    hourly_for_15 = pd.merge_asof(m15[["time_key"]], hourly[["time_key", "close", "ma20"]], on="time_key", direction="backward", allow_exact_matches=False)
    daily_for_15 = pd.merge_asof(m15[["time_key"]], d1[["time_key", "close", "ma20", "ma50"]], on="time_key", direction="backward", allow_exact_matches=False)
    last = -10**9
    for i, bar in m15.iterrows():
        if i - last < 20 or pd.isna(bar.prior_high20) or pd.isna(bar.volume_ma20):
            continue
        h, d = hourly_for_15.iloc[i], daily_for_15.iloc[i]
        if pd.isna(h.ma20) or pd.isna(d.ma20) or pd.isna(d.ma50):
            continue
        if not (d.close > d.ma20 > d.ma50 and h.close > h.ma20 and bar.close > bar.prior_high20 and bar.volume > 1.2 * bar.volume_ma20):
            continue
        stop = min(float(bar.prior_low20), float(bar.close) - 1.5 * float(bar.atr20))
        if stop <= 0 or stop >= float(bar.close):
            continue
        rows.append(_make_signal("II", symbol, bar, i, stop, hashes, "D1+1H+15m closed breakout", "15m"))
        last = i
    # III: D1+1H only.  No m15 columns are accessed here; execution is next 1H open.
    daily_for_1h = pd.merge_asof(hourly[["time_key"]], d1[["time_key", "close", "ma20", "ma50"]], on="time_key", direction="backward", allow_exact_matches=False)
    last = -10**9
    for i, bar in hourly.iterrows():
        if i - last < 5 or pd.isna(bar.prior_high20) or pd.isna(bar.volume_ma20):
            continue
        d = daily_for_1h.iloc[i]
        if pd.isna(bar.ma20) or pd.isna(d.ma20) or pd.isna(d.ma50):
            continue
        if not (d.close > d.ma20 > d.ma50 and bar.close > bar.ma20 and bar.close > bar.prior_high20 and bar.volume > 1.2 * bar.volume_ma20):
            continue
        stop = min(float(bar.prior_low20), float(bar.close) - 1.5 * float(bar.atr20))
        if stop <= 0 or stop >= float(bar.close):
            continue
        rows.append(_make_signal("III", symbol, bar, i, stop, hashes, "D1+1H closed breakout", "1H"))
        last = i
    return rows


def _make_signal(protocol: str, symbol: str, bar: pd.Series, index: int, stop: float, hashes: dict[str, str], rule: str, execution_tf: str) -> dict:
    entry = float(bar.close)
    return {"protocol": protocol, "symbol": symbol, "sector": SECTOR[symbol], "market_regime": "TREND_UP", "signal_time": bar.time_key.isoformat(), "signal_available_at": bar.time_key.isoformat(), "execution_timeframe": execution_tf, "entry_index": int(index) + 1, "signal_close": entry, "stop_price": stop, "target_price": entry + 2 * (entry - stop), "risk_budget": RISK_BUDGET, "rule": rule, "data_hash_15m": hashes["15m"], "data_hash_1h": hashes["1H"], "data_hash_d1": hashes["D1"], "quality": "UNKNOWN_TIMEZONE_DST_CALENDAR_BAR_CLOSURE_PROVIDER_FINALITY"}


def _risk_replay(signal: dict, m5: pd.DataFrame, signal_frame: pd.DataFrame, equity: float) -> dict:
    entry_i = signal["entry_index"]
    if entry_i >= len(signal_frame):
        return {"status": "OPEN_NO_FUTURE_BAR", "entry_price": None, "exit_price": None, "net_return": None, "units": 0.0}
    entry_time = signal_frame.iloc[entry_i].time_key
    candidates = m5[m5.time_key >= entry_time]
    if candidates.empty:
        return {"status": "OPEN_NO_5M_AUDIT", "entry_price": float(signal_frame.iloc[entry_i].open), "exit_price": None, "net_return": None, "units": 0.0}
    entry = float(signal_frame.iloc[entry_i].open)
    stop, target = float(signal["stop_price"]), float(signal["target_price"])
    risk = entry - stop
    units = equity * RISK_BUDGET / risk
    exit_price = None; exit_time = None; reason = "OPEN_NO_EXIT"; gap = False; conflict = False; floating_low = 0.0
    for _, bar in candidates.iloc[: 80 * (12 if signal["execution_timeframe"] == "15m" else 48)].iterrows():
        floating_low = min(floating_low, units * (float(bar.low) - entry))
        if float(bar.open) <= stop:
            exit_price, exit_time, reason, gap = float(bar.open), bar.time_key, "GAP_STOP", True
            break
        hit_stop, hit_target = float(bar.low) <= stop, float(bar.high) >= target
        if hit_stop and hit_target:
            exit_price, exit_time, reason, conflict = stop, bar.time_key, "STOP_SAME_BAR_CONSERVATIVE", True
            break
        if hit_stop:
            exit_price, exit_time, reason = stop, bar.time_key, "STOP"
            break
        if hit_target:
            exit_price, exit_time, reason = target, bar.time_key, "TARGET"
            break
    if exit_price is None:
        last = candidates.iloc[min(len(candidates) - 1, 80 * (12 if signal["execution_timeframe"] == "15m" else 48) - 1)]
        exit_price, exit_time, reason = float(last.close), last.time_key, "OPEN_CENSORED_AT_WINDOW"
    net = (exit_price * (1 - COST_BPS / 10000) / (entry * (1 + COST_BPS / 10000)) - 1.0)
    return {"status": "PASS", "entry_price": entry, "entry_time": entry_time.isoformat(), "exit_price": exit_price, "exit_time": exit_time.isoformat(), "exit_reason": reason, "gap_stop": gap, "same_bar_stop_target_conflict": conflict, "units": units, "gross_pnl": units * (exit_price - entry), "net_pnl": units * (exit_price - entry) - units * entry * 2 * COST_BPS / 10000, "net_return": net, "floating_low_pnl": floating_low}


def run(capture: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    all_signals: list[dict] = []; source_manifest = []; prepared: dict[str, dict[str, pd.DataFrame]] = {}
    for symbol in SYMBOLS:
        paths = {tf: capture / f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv" for tf in ("D1", "1H", "15m", "5m")}
        if not all(p.exists() for p in paths.values()):
            continue
        frames = {tf: _indicators(_read(paths[tf])) for tf in paths}
        prepared[symbol] = frames
        hashes = {tf: _hash(paths[tf]) for tf in paths}
        for tf in paths:
            source_manifest.append({"symbol": symbol, "timeframe": tf, "path": str(paths[tf]), "rows": len(frames[tf]), "sha256": hashes[tf]})
        all_signals += _signals(symbol, frames, hashes)
    signal_df = pd.DataFrame(all_signals)
    if signal_df.empty:
        raise RuntimeError("no signals generated")
    accepted = []; active: list[tuple[pd.Timestamp, str]] = []; equity = 100000.0; open_until: dict[str, pd.Timestamp] = {}; sector_count: dict[str, int] = {}
    for _, row in signal_df.sort_values("signal_time").iterrows():
        ts = pd.Timestamp(row.signal_time); sector = row.sector
        still_active = [(exit_at, active_sector) for exit_at, active_sector in active if exit_at > ts]
        active = still_active
        sector_count = {name: sum(1 for _, active_sector in active if active_sector == name) for name in set(name for _, name in active)}
        if len(active) >= 3 or sector_count.get(sector, 0) >= 2 or ts < open_until.get(row.symbol, pd.Timestamp.min):
            continue
        symbol_frames = prepared[row.symbol]
        audit = _risk_replay(row.to_dict(), symbol_frames["5m"], symbol_frames[row.execution_timeframe], equity)
        accepted.append({**row.to_dict(), **audit, "portfolio_equity_before": equity})
        if audit.get("net_pnl") is not None:
            equity += float(audit["net_pnl"])
        exit_at = pd.Timestamp(audit.get("exit_time", row.signal_time))
        open_until[row.symbol] = exit_at
        active.append((exit_at, sector))
        sector_count[sector] = sector_count.get(sector, 0) + 1
    trades = pd.DataFrame(accepted)
    trades.to_csv(out / "round10_executable_trade_ledger.csv", index=False)
    signal_df.to_csv(out / "round10_signal_ledger.csv", index=False)
    metrics = []
    for protocol, group in trades.groupby("protocol"):
        pnls = pd.to_numeric(group.net_pnl, errors="coerce").dropna(); wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
        cumulative = pnls.cumsum(); event_mdd = float((cumulative.cummax() - cumulative).max()) if not cumulative.empty else 0.0
        floating_mdd = float(abs(pd.to_numeric(group.floating_low_pnl, errors="coerce").min())) if not group.empty else 0.0
        metrics.append({"protocol": protocol, "trades": len(group), "net_pnl": float(pnls.sum()), "return_pct_on_100k": float(pnls.sum() / 100000 * 100), "profit_factor": float(wins.sum() / abs(losses.sum())) if not losses.empty else None, "event_mdd_pnl": event_mdd, "floating_mdd_5m_pnl": floating_mdd, "cost_bps_per_side": COST_BPS, "risk_budget": RISK_BUDGET, "open_censored": int((group.exit_reason == "OPEN_CENSORED_AT_WINDOW").sum()), "stop": int(group.exit_reason.astype(str).str.contains("STOP").sum()), "target": int((group.exit_reason == "TARGET").sum())})
    pd.DataFrame(metrics).to_csv(out / "round10_backtest_comparison.csv", index=False)
    regime = signal_df.groupby(["protocol", "market_regime"]).size().reset_index(name="signals")
    regime = regime.set_index(["protocol", "market_regime"]).reindex(pd.MultiIndex.from_product([["II", "III"], ["TREND_UP", "TREND_DOWN", "RANGE", "UNKNOWN"]], names=["protocol", "market_regime"]), fill_value=0).reset_index()
    regime.to_csv(out / "round10_regime_comparison.csv", index=False)
    annual = trades.assign(year=pd.to_datetime(trades.signal_time).dt.year).groupby(["protocol", "year"], as_index=False).agg(trades=("protocol", "size"), net_pnl=("net_pnl", "sum"))
    annual.to_csv(out / "round10_annual_distribution.csv", index=False)
    status = {"schema_version": "stock-razor-round10-radar-replay-v0.1", "status": "RESEARCH_ONLY", "base_commit": "e43ad28dec3d264560cd3cfbebb069ecb02f35a8", "replay_lab_compatibility": "BLOCKED_INCOMPATIBLE_VIBE_PROXY", "signal_rows": len(signal_df), "accepted_trade_rows": len(trades), "source_manifest": source_manifest, "quality": {"timezone": "UNKNOWN", "dst_calendar": "UNKNOWN", "bar_closure": "UNKNOWN", "provider_finality": "UNKNOWN", "a_share_tickflow": "NOT_VERIFIED"}, "safety": {"RADAR_ADMISSION": "BLOCKED", "PAPER_AUTO_READY": "NO", "LIVE_TRADE": "NO", "TRADE_EXECUTION": "NO"}, "limits": {"max_positions": 3, "max_same_sector": 2, "risk_budget": RISK_BUDGET, "cost_bps_per_side": COST_BPS, "m5_role": "OFFLINE_RISK_STOP_AUDIT_ONLY", "one_minute": "EXCLUDED"}}
    (out / "round10_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.capture, args.out), ensure_ascii=False, indent=2, default=str))

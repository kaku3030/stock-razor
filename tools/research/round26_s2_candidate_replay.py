"""Round26 S2 candidate replay. Research only; no provider calls or orders."""
from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS = ("AAPL", "AMD", "COHR", "NVDA", "QQQ", "TSLA")
TIMEFRAMES = ("D1", "1H", "15m", "5m", "1m")
SECTOR = {"AAPL": "TECH", "AMD": "SEMIS", "COHR": "SEMIS", "NVDA": "SEMIS", "QQQ": "ETF", "TSLA": "AUTO"}
COSTS_BPS = (5.0, 10.0, 20.0)
INITIAL_EQUITY = 100_000.0
RISK_FRACTION = 0.0025
MAX_POSITIONS = 3
MAX_SECTOR_POSITIONS = 2


def read_bars(path: Path, timestamp_zone: str, timeframe: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"time_key", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    stamps = pd.to_datetime(frame.time_key, errors="raise")
    if stamps.dt.tz is None:
        stamps = stamps.dt.tz_localize(timestamp_zone, ambiguous="raise", nonexistent="raise")
    else:
        stamps = stamps.dt.tz_convert(timestamp_zone)
    frame["time_key"] = stamps
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="raise")
        if not np.isfinite(frame[col].to_numpy(dtype=float)).all():
            raise ValueError(f"{path}: non-finite {col}")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any() or (frame.volume < 0).any():
        raise ValueError(f"{path}: non-positive OHLC or negative volume")
    bad = (frame.high < frame[["open", "close", "low"]].max(axis=1)) | (frame.low > frame[["open", "close", "high"]].min(axis=1))
    if bad.any():
        rows = frame.loc[bad, ["time_key", "open", "high", "low", "close", "volume"]].head(5)
        raise ValueError(f"{path}: invalid OHLC rows: {rows.to_dict('records')}")
    if frame.time_key.duplicated().any():
        raise ValueError(f"{path}: duplicate timestamps")
    if not frame.time_key.is_monotonic_increasing:
        raise ValueError(f"{path}: timestamps not strictly ordered")
    if timeframe == "1m":
        local = frame.time_key.dt.tz_convert("America/New_York")
        for day, indexes in local.groupby(local.dt.date).groups.items():
            day_times = local.loc[indexes]
            first = day_times.iloc[0]
            last = day_times.iloc[-1]
            if (first.hour, first.minute) != (9, 31) or (last.hour, last.minute) not in {(13, 0), (16, 0)}:
                raise ValueError(f"{path}: unexpected RTH 1m session endpoints on {day}: {first} .. {last}")
            expected = pd.date_range(first, last, freq="1min")
            if not day_times.reset_index(drop=True).equals(pd.Series(expected)):
                raise ValueError(f"{path}: missing or irregular 1m RTH bars on {day}")
    return frame.reset_index(drop=True)


def add_features(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["prior_high20"] = out.high.rolling(20, min_periods=20).max().shift(1)
    out["prior_low20"] = out.low.rolling(20, min_periods=20).min().shift(1)
    out["prior_volume_mean20"] = out.volume.rolling(20, min_periods=20).mean().shift(1)
    out["prior_range_mean20"] = (out.high - out.low).rolling(20, min_periods=20).mean().shift(1)
    out["sma20"] = out.close.rolling(20, min_periods=20).mean()
    out["sma50"] = out.close.rolling(50, min_periods=50).mean()
    return out


def _latest_before(frame: pd.DataFrame, timestamp: pd.Timestamp) -> pd.Series | None:
    pos = int(frame.time_key.searchsorted(timestamp, side="left")) - 1
    return None if pos < 0 else frame.iloc[pos]


def _breakout(row: pd.Series) -> bool:
    values = (row.get("prior_high20"), row.get("prior_volume_mean20"))
    if any(pd.isna(x) for x in values) or float(row.prior_volume_mean20) <= 0:
        return False
    return float(row.close) > float(row.prior_high20) and float(row.volume) > 1.2 * float(row.prior_volume_mean20)


def generate_signals(frames: dict[str, pd.DataFrame], symbol: str) -> list[dict]:
    d1, h1, m15, m5, m1 = (frames[x] for x in TIMEFRAMES)
    result: list[dict] = []
    last_m15_index = -10**9
    for i, row15 in m15.iterrows():
        if i - last_m15_index < 20 or not _breakout(row15):
            continue
        d, h = _latest_before(d1, row15.time_key), _latest_before(h1, row15.time_key)
        if d is None or h is None or any(pd.isna(v) for v in (d.get("sma20"), d.get("sma50"), h.get("sma20"))):
            continue
        if not (float(d.close) > float(d.sma20) > float(d.sma50) and float(h.close) > float(h.sma20)):
            continue
        if pd.isna(row15.prior_low20) or pd.isna(row15.prior_range_mean20):
            continue
        stop = min(float(row15.prior_low20), float(row15.close) - 1.5 * float(row15.prior_range_mean20))
        if not math.isfinite(stop) or stop <= 0 or stop >= float(row15.close):
            continue
        date15 = row15.time_key.date()
        m5_after = m5[(m5.time_key > row15.time_key) & (m5.time_key.dt.date == date15)].head(3)
        confirm5 = next((x for _, x in m5_after.iterrows() if _breakout(x)), None)
        if confirm5 is None:
            last_m15_index = i
            continue
        m1_after = m1[(m1.time_key > confirm5.time_key) & (m1.time_key.dt.date == date15)].head(5)
        confirm1 = next((x for _, x in m1_after.iterrows() if _breakout(x)), None)
        if confirm1 is None:
            last_m15_index = i
            continue
        entry_pos = int(m1.time_key.searchsorted(confirm1.time_key, side="right"))
        if entry_pos >= len(m1):
            last_m15_index = i
            continue
        entry = m1.iloc[entry_pos]
        et = entry.time_key.tz_convert("America/New_York")
        if entry.time_key.date() != date15 or not (9 * 60 + 36 <= et.hour * 60 + et.minute <= 15 * 60 + 30):
            last_m15_index = i
            continue
        entry_price = float(entry.open)
        if entry_price <= stop:
            last_m15_index = i
            continue
        risk = entry_price - stop
        target = entry_price + 2.0 * risk
        session = m1[m1.time_key.dt.date == date15]
        entry_global = int(entry_pos)
        session_positions = session.index.to_list()
        after = [idx for idx in session_positions if idx >= entry_global][:80]
        if not after:
            last_m15_index = i
            continue
        last_candidate = after[-1]
        exit_price = float(m1.iloc[last_candidate].close)
        exit_time = m1.iloc[last_candidate].time_key
        reason = "TIME_80_BARS"
        for idx in after:
            bar = m1.iloc[idx]
            op, lo, hi = float(bar.open), float(bar.low), float(bar.high)
            if op <= stop:
                exit_price, exit_time, reason = op, bar.time_key, "GAP_STOP"
                break
            hit_stop, hit_target = lo <= stop, hi >= target
            if hit_stop:
                exit_price, exit_time, reason = stop, bar.time_key, "STOP_SAME_BAR_CONSERVATIVE" if hit_target else "STOP"
                break
            if hit_target:
                exit_price, exit_time, reason = target, bar.time_key, "TARGET"
                break
        if last_candidate == session_positions[-1] and reason == "TIME_80_BARS":
            reason = "RTH_CLOSE"
        result.append({
            "symbol": symbol, "sector": SECTOR[symbol], "signal_time": row15.time_key,
            "confirm_5m_time": confirm5.time_key, "confirm_1m_time": confirm1.time_key,
            "entry_time": entry.time_key, "entry_price": entry_price, "stop_price": stop,
            "target_price": target, "exit_time": exit_time, "exit_price": exit_price,
            "exit_reason": reason, "risk_per_share": risk,
        })
        last_m15_index = i
    return result


def portfolio_replay(signals: list[dict], close_by_symbol: dict[str, pd.Series], cost_bps: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    fee = cost_bps / 10_000.0
    cash = INITIAL_EQUITY
    active: list[dict] = []
    trades: list[dict] = []
    for signal in sorted(signals, key=lambda x: (x["entry_time"], x["symbol"])):
        ts = signal["entry_time"]
        still = []
        for position in active:
            if position["exit_time"] <= ts:
                cash += position["units"] * position["exit_price"] * (1 - fee)
            else:
                still.append(position)
        active = still
        sector_count = sum(p["sector"] == signal["sector"] for p in active)
        if len(active) >= MAX_POSITIONS or sector_count >= MAX_SECTOR_POSITIONS or any(p["symbol"] == signal["symbol"] for p in active):
            continue
        mark_values = 0.0
        for p in active:
            prices = close_by_symbol[p["symbol"]]
            eligible = prices.loc[:ts]
            if eligible.empty:
                raise ValueError(f"no mark for {p['symbol']} at {ts}")
            mark_values += p["units"] * float(eligible.iloc[-1])
        equity = cash + mark_values
        risk = float(signal["risk_per_share"])
        units = math.floor((equity * RISK_FRACTION / risk) * 1000) / 1000
        affordable = math.floor((cash / (float(signal["entry_price"]) * (1 + fee))) * 1000) / 1000
        units = min(units, affordable)
        if units < 0.001:
            continue
        entry_cost = units * float(signal["entry_price"]) * (1 + fee)
        exit_proceeds = units * float(signal["exit_price"]) * (1 - fee)
        cash -= entry_cost
        pnl = exit_proceeds - entry_cost
        position = {**signal, "units": units, "entry_cost": entry_cost, "net_pnl": pnl}
        trades.append(position)
        active.append(position)
    for position in sorted(active, key=lambda x: x["exit_time"]):
        cash += position["units"] * position["exit_price"] * (1 - fee)
    trade_frame = pd.DataFrame(trades)
    if trade_frame.empty:
        trade_frame = pd.DataFrame(columns=["symbol", "sector", "signal_time", "entry_time", "exit_time", "entry_price", "exit_price", "units", "net_pnl"])
    all_times = pd.DatetimeIndex(sorted(set().union(*(set(s.index) for s in close_by_symbol.values()))))
    cash_changes = pd.Series(0.0, index=all_times)
    holdings = pd.DataFrame(0.0, index=all_times, columns=close_by_symbol.keys())
    for t in trades:
        cash_changes.loc[t["entry_time"]] -= t["entry_cost"]
        cash_changes.loc[t["exit_time"]] += t["units"] * t["exit_price"] * (1 - fee)
        mask = (all_times >= t["entry_time"]) & (all_times < t["exit_time"])
        holdings.loc[mask, t["symbol"]] += t["units"]
    prices = pd.DataFrame({s: values.reindex(all_times).ffill() for s, values in close_by_symbol.items()})
    cash_curve = INITIAL_EQUITY + cash_changes.cumsum()
    market_value = (holdings * prices).sum(axis=1)
    curve = pd.DataFrame({"time_key": all_times, "cash": cash_curve.values, "holdings_market_value": market_value.values})
    curve["equity"] = curve.cash + curve.holdings_market_value
    curve["peak"] = curve.equity.cummax()
    curve["drawdown"] = curve.peak - curve.equity
    return trade_frame, curve


def summarize(trades: pd.DataFrame, curve: pd.DataFrame, cost: float) -> list[dict]:
    periods = {"full_2019_2026": (None, None), "train_2019_2023": ("2019-01-01", "2023-12-31 23:59:59"), "oos_2024_2026": ("2024-01-01", "2026-10-16 23:59:59")}
    rows = []
    for name, (start, end) in periods.items():
        if trades.empty or start is None:
            tg = trades
        else:
            tg = trades[(trades.entry_time >= pd.Timestamp(start, tz="America/New_York")) & (trades.entry_time <= pd.Timestamp(end, tz="America/New_York"))]
        cg = curve if start is None else curve[(curve.time_key >= pd.Timestamp(start, tz="America/New_York")) & (curve.time_key <= pd.Timestamp(end, tz="America/New_York"))]
        pnl = pd.to_numeric(tg.net_pnl, errors="coerce") if not tg.empty else pd.Series(dtype=float)
        wins, losses = pnl[pnl > 0], pnl[pnl < 0]
        if cg.empty:
            mdd = 0.0
        else:
            start_equity = float(cg.equity.iloc[0])
            running_peak = np.maximum.accumulate(np.r_[start_equity, cg.equity.to_numpy()])
            dd = running_peak[1:] - cg.equity.to_numpy()
            mdd = float(dd.max()) if len(dd) else 0.0
        dd_pct = float((dd / running_peak[1:]).max()) if len(dd) else 0.0
        rows.append({"strategy": "S2_CANDIDATE", "window": name, "cost_bps_per_side": cost,
                     "trades": int(len(tg)), "net_pnl": float(pnl.sum()),
                     "profit_factor": float(wins.sum() / abs(losses.sum())) if not losses.empty else None,
                     "max_drawdown": mdd, "max_drawdown_pct": dd_pct,
                     "win_rate": float((pnl > 0).mean()) if len(pnl) else None,
                     "expectancy": float(pnl.mean()) if len(pnl) else None})
    return rows


def run(capture: Path, out: Path, timestamp_zone: str) -> None:
    if timestamp_zone != "America/New_York":
        raise ValueError("Round26 candidate requires the audited America/New_York timezone")
    out.mkdir(parents=True, exist_ok=True)
    prepared: dict[str, dict[str, pd.DataFrame]] = {}
    signals: list[dict] = []
    manifest = []
    for symbol in SYMBOLS:
        frames = {}
        for tf in TIMEFRAMES:
            path = capture / f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv"
            frame = add_features(read_bars(path, timestamp_zone, tf))
            frames[tf] = frame
            manifest.append({"symbol": symbol, "timeframe": tf, "rows": len(frame), "first": str(frame.time_key.iloc[0]), "last": str(frame.time_key.iloc[-1]), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        prepared[symbol] = frames
        signals.extend(generate_signals(frames, symbol))
    pd.DataFrame(manifest).to_csv(out / "s2_candidate_manifest.csv", index=False)
    pd.DataFrame(signals).to_csv(out / "s2_candidate_signals.csv", index=False)
    close_by_symbol = {s: f["1m"].set_index("time_key").close for s, f in prepared.items()}
    all_trades, all_curves, summary = [], [], []
    for cost in COSTS_BPS:
        trades, curve = portfolio_replay(signals, close_by_symbol, cost)
        trades["cost_bps_per_side"] = cost
        curve["cost_bps_per_side"] = cost
        all_trades.append(trades); all_curves.append(curve)
        summary.extend(summarize(trades, curve, cost))
    pd.concat(all_trades, ignore_index=True).to_csv(out / "s2_candidate_trade_ledger.csv", index=False)
    pd.concat(all_curves, ignore_index=True).to_csv(out / "s2_candidate_equity_curve.csv", index=False)
    pd.DataFrame(summary).to_csv(out / "s2_candidate_metrics.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--timestamp-zone", required=True, help="Timezone declared by the audited capture, e.g. America/New_York")
    args = parser.parse_args()
    run(args.capture, args.out, args.timestamp_zone)

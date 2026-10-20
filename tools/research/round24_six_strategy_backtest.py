"""Round24 unified historical replay on frozen local OpenD captures (research only)."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research import round10_radar_replay as r10
from tools.research import round11_radar_research as r11
from tools.research import round13_radar_research as r13
from tools.research.round16_research import build_s1_srvp_signals, qualify_s2_coverage

COSTS_BPS = (5.0, 10.0, 20.0)
BASE_SIZING_COST_BPS = 10.0
SYMBOLS = tuple(r13.ROUND10_SYMBOLS)
TIMEFRAMES = ("D1", "1H", "15m", "5m")
WINDOWS = {
    "full_2019_2026": (pd.Timestamp("2019-01-01"), pd.Timestamp("2026-10-16 23:59:59")),
    "train_2019_2023": (pd.Timestamp("2019-01-01"), pd.Timestamp("2023-12-31 23:59:59")),
    "oos_2024_2026": (pd.Timestamp("2024-01-01"), pd.Timestamp("2026-10-16 23:59:59")),
}


def capture_path(capture: Path, symbol: str, timeframe: str) -> Path:
    return capture / f"US_{symbol}_{timeframe}_qfq_rth_20190101_20261016.csv"


def _load_capture(capture: Path) -> tuple[dict, list[dict]]:
    prepared, manifest = {}, []
    for symbol in SYMBOLS:
        frames = {}
        for tf in TIMEFRAMES:
            path = capture_path(capture, symbol, tf)
            if not path.is_file():
                raise ValueError(f"missing capture: {symbol}/{tf}")
            frame = r13._read(path)
            if frame.empty or frame.time_key.isna().any():
                raise ValueError(f"empty or invalid timestamps: {symbol}/{tf}")
            if not frame.time_key.is_monotonic_increasing or frame.time_key.duplicated().any():
                raise ValueError(f"timestamps are not strictly ordered: {symbol}/{tf}")
            fields = [column for column in ("open", "high", "low", "close", "volume") if column in frame]
            values = frame[fields].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
            if not np.isfinite(values).all() or (frame[["open", "high", "low", "close"]].astype(float) <= 0).any().any():
                raise ValueError(f"non-finite or non-positive OHLCV: {symbol}/{tf}")
            if "volume" in frame and (pd.to_numeric(frame.volume, errors="coerce") < 0).any():
                raise ValueError(f"negative volume: {symbol}/{tf}")
            frames[tf] = frame
            manifest.append({
                "symbol": symbol, "timeframe": tf, "rows": int(len(frame)),
                "first_time_key": str(frame.time_key.iloc[0]),
                "last_time_key": str(frame.time_key.iloc[-1]),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            })
        prepared[symbol] = frames
    return prepared, manifest


def _load_cached_radar(reference: Path, manifest: list[dict]) -> tuple[pd.DataFrame, dict]:
    baseline = reference / "round13_baseline"
    fusion = reference / "round14_fusion"
    status13 = json.loads((baseline / "round13_status.json").read_text(encoding="utf-8"))
    status14 = json.loads((fusion / "round14_srvp_fusion_status.json").read_text(encoding="utf-8"))
    hash_map = {(row["symbol"], row["timeframe"]): row["sha256"] for row in manifest}
    expected = {(row["symbol"], row["timeframe"]): row["sha256"] for row in status13["source_manifest"]}
    if hash_map != expected:
        raise ValueError("Round13 frozen cache does not match the current 24 raw capture SHA256 values")
    expected14 = {(row["symbol"], row["timeframe"]): row["sha256"] for row in status14["source_manifest"]}
    if expected14 != hash_map:
        raise ValueError("Round14 SRVP cache does not match the current 24 raw capture SHA256 values")

    radar = pd.read_csv(baseline / "round13_signal_ledger.csv")
    confirmed = pd.read_csv(fusion / "round14_srvp_confirmation_ledger.csv")
    keys = ["protocol", "symbol", "signal_time"]
    radar["signal_time"] = pd.to_datetime(radar.signal_time, errors="raise")
    confirmed["signal_time"] = pd.to_datetime(confirmed.signal_time, errors="raise")
    if radar.duplicated(keys).any() or confirmed.duplicated(keys).any():
        raise ValueError("cached signal keys are not unique")
    flags = confirmed[keys + ["srvp_1h_confirm", "srvp_15m_confirm"]]
    merged = radar.merge(flags, on=keys, how="left", validate="one_to_one", indicator=True)
    if len(merged) != len(radar) or not (merged._merge == "both").all():
        raise ValueError("Round13 and Round14 signal ledgers do not have exact key parity")
    for row in merged.itertuples():
        for tf, col in (("15m", "data_hash_15m"), ("1H", "data_hash_1h"), ("D1", "data_hash_d1")):
            if getattr(row, col) != hash_map[(row.symbol, tf)]:
                raise ValueError(f"signal data hash mismatch for {row.symbol}/{tf}")
    merged["srvp_1h_confirm"] = merged.srvp_1h_confirm.astype(bool)
    merged["srvp_15m_confirm"] = merged.srvp_15m_confirm.astype(bool)
    cache_meta = {
        "round13_status_sha256": hashlib.sha256((baseline / "round13_status.json").read_bytes()).hexdigest(),
        "round14_status_sha256": hashlib.sha256((fusion / "round14_srvp_fusion_status.json").read_bytes()).hexdigest(),
        "round13_signal_rows": int(len(radar)),
        "round14_confirmation_rows": int(len(confirmed)),
        "signal_key_parity": "PASS",
    }
    return merged, cache_meta


def _build_arms(capture: Path, prepared: dict, radar: pd.DataFrame) -> tuple[dict, dict]:
    arms = {
        "S3": (radar[(radar.protocol == "III") & radar.srvp_1h_confirm].copy(), "III"),
        "S4": (radar[(radar.protocol == "II") & radar.srvp_15m_confirm].copy(), "II"),
        "S5": (radar[radar.protocol == "III"].copy(), "III"),
        "S6": (radar[radar.protocol == "II"].copy(), "II"),
    }
    s1_rows = []
    for symbol, frames in prepared.items():
        hashes = {tf: hashlib.sha256(capture_path(capture, symbol, tf).read_bytes()).hexdigest()
                  for tf in TIMEFRAMES}
        signal = build_s1_srvp_signals(symbol, frames, hashes)
        if not signal.empty:
            s1_rows.append(signal)
    s1 = pd.concat(s1_rows, ignore_index=True) if s1_rows else pd.DataFrame(
        columns=["protocol", "symbol", "signal_time", "execution_timeframe"]
    )
    arms["S1"] = (s1, "S1")
    status = {
        "S1": {"status": "RUNNABLE", "signals": int(len(s1)), "definition": "standalone 1H SRVP near-VAL trigger"},
        "S2": {"status": "BLOCKED", "reason": "genuine historical 1m bars absent; test fixtures excluded"},
        "S3": {"status": "RUNNABLE", "signals": int(len(arms["S3"][0])), "definition": "Radar D1+1H with 1H SRVP entry-confirmation filter"},
        "S4": {"status": "RUNNABLE", "signals": int(len(arms["S4"][0])), "definition": "Radar D1+1H+15m with 15m SRVP entry-confirmation filter"},
        "S5": {"status": "RUNNABLE", "signals": int(len(arms["S5"][0])), "definition": "Radar D1+1H"},
        "S6": {"status": "RUNNABLE", "signals": int(len(arms["S6"][0])), "definition": "Radar D1+1H+15m"},
    }
    return arms, status


def _buy_hold(prepared: dict, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    series = {}
    for symbol, frames in prepared.items():
        close = frames["D1"].set_index("time_key")["close"].astype(float)
        close = close[(close.index >= start) & (close.index <= end)]
        if not close.empty:
            series[symbol] = close
    prices = pd.concat(series, axis=1).sort_index().ffill().dropna()
    if prices.empty:
        return {"return": None, "mdd": None, "mdd_pct": None, "final_equity": None, "symbols": 0}
    equity = 100000.0 * (prices / prices.iloc[0]).mean(axis=1)
    drawdown = equity.cummax() - equity
    return {"return": float(equity.iloc[-1] / equity.iloc[0] - 1),
            "mdd": float(drawdown.max()), "mdd_pct": float((drawdown / equity.cummax()).max()),
            "final_equity": float(equity.iloc[-1]), "symbols": int(prices.shape[1])}


def _vectorized_curve(trades: pd.DataFrame, prepared: dict, cost_bps: float) -> pd.DataFrame:
    """Match legacy cash/mark-to-market accounting in O(bars + trades)."""
    timestamps = pd.DatetimeIndex(sorted({ts for symbol in prepared for ts in prepared[symbol]["5m"].time_key}))
    if not timestamps.is_unique or not timestamps.is_monotonic_increasing:
        raise ValueError("5m timeline must be sorted and unique")
    cash_events = np.zeros(len(timestamps))
    holdings = np.zeros(len(timestamps))
    open_cost = np.zeros(len(timestamps))
    rate = float(cost_bps) / 10000.0
    for symbol, group in trades.groupby("symbol", sort=False) if not trades.empty else []:
        entry_ix = timestamps.get_indexer(pd.to_datetime(group.entry_time))
        exit_ix = timestamps.get_indexer(pd.to_datetime(group.exit_time))
        if (entry_ix < 0).any() or (exit_ix < entry_ix).any():
            raise ValueError("trade timestamps must be on the 5m timeline and ordered")
        units = pd.to_numeric(group.units, errors="raise").to_numpy(dtype=float)
        entry = pd.to_numeric(group.entry_price, errors="raise").to_numpy(dtype=float)
        exit_ = pd.to_numeric(group.exit_price, errors="raise").to_numpy(dtype=float)
        if not np.isfinite(np.column_stack([units, entry, exit_])).all() or (units <= 0).any() or (entry <= 0).any() or (exit_ <= 0).any():
            raise ValueError("trade prices and units must be finite and positive")
        np.add.at(cash_events, entry_ix, -entry * units * (1 + rate))
        np.add.at(cash_events, exit_ix, exit_ * units * (1 - rate))
        unit_events = np.zeros(len(timestamps))
        np.add.at(unit_events, entry_ix, units)
        np.add.at(unit_events, exit_ix, -units)
        cost_events = np.zeros(len(timestamps))
        np.add.at(cost_events, entry_ix, entry * units)
        np.add.at(cost_events, exit_ix, -entry * units)
        units_held, cost_held = np.cumsum(unit_events), np.cumsum(cost_events)
        close = (prepared[symbol]["5m"].set_index("time_key")["close"]
                 .astype(float).reindex(timestamps).ffill().fillna(0.0).to_numpy())
        active = units_held != 0
        if not np.isfinite(close[active]).all() or (close[active] <= 0).any():
            raise ValueError(f"missing/invalid active price for {symbol}")
        holdings += units_held * close
        open_cost += cost_held
    cash = 100000.0 + np.cumsum(cash_events)
    if (cash < -1e-7).any():
        raise ValueError("cash became negative under this cost scenario")
    equity = cash + holdings
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    return pd.DataFrame({"time_key": timestamps, "cash": cash, "holdings_market_value": holdings,
                         "unrealized_pnl": holdings - open_cost, "total_equity": equity,
                         "drawdown": drawdown, "running_peak": peak,
                         "accounting_residual": equity - cash - holdings})


def _metric(strategy: str, window: str, cost: float, trades: pd.DataFrame,
            curve: pd.DataFrame, benchmark: dict) -> dict:
    pnl = pd.to_numeric(trades.get("net_pnl", pd.Series(dtype=float)), errors="coerce").dropna()
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    mdd = float(curve.drawdown.max()) if not curve.empty else 0.0
    mdd_pct = float((curve.drawdown / curve.running_peak).max()) if not curve.empty else 0.0
    return {"strategy": strategy, "window": window, "cost_bps_per_side": cost,
            "trades": int(len(trades)), "net_pnl": float(pnl.sum()),
            "profit_factor": float(wins.sum() / abs(losses.sum())) if not losses.empty else None,
            "max_drawdown": mdd, "max_drawdown_pct": mdd_pct,
            "win_rate": float((pnl > 0).mean()) if len(pnl) else None,
            "expectancy": float(pnl.mean()) if len(pnl) else None,
            "final_equity": float(curve.total_equity.iloc[-1]) if not curve.empty else 100000.0,
            "buy_hold_return": benchmark["return"], "buy_hold_max_drawdown": benchmark["mdd"],
            "buy_hold_max_drawdown_pct": benchmark["mdd_pct"],
            "buy_hold_final_equity": benchmark["final_equity"]}


def _write_report(out: Path, status: dict, metrics: pd.DataFrame) -> None:
    full = metrics[(metrics.window == "full_2019_2026") & (metrics.cost_bps_per_side == 10)]
    oos = metrics[(metrics.window == "oos_2024_2026") & (metrics.cost_bps_per_side == 10)]
    rows = full.set_index("strategy").join(oos.set_index("strategy"), lsuffix="_full", rsuffix="_oos")
    fmt = lambda value: "—" if pd.isna(value) else f"{value:,.2f}"
    lines = [
        "# Round24: unified six-strategy historical replay", "",
        "**Status: PARTIAL_DATA_BLOCKED.** S1 and S3–S6 were rerun on the same frozen six-symbol Futu/OpenD capture. S2 is blocked because genuine historical 1m bars are absent; a Round22 test fixture was excluded.",
        "",
        "The Round13 signal ledger and Round14 SRVP confirmation ledger both match all 24 raw capture SHA256 values. S3/S4 use SRVP as an entry-confirmation filter. At each 5/10/20 bps per-side scenario, the same signals are replayed with scenario-specific sizing and costs under the cash constraint.",
        "",
        "## 10 bps/side comparison", "",
        "| Arm | Full net P&L | Full PF | Full MDD | Full trades | Full win rate | OOS net P&L | OOS PF | OOS MDD | OOS trades | OOS win rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy in ("S1", "S2", "S3", "S4", "S5", "S6"):
        if strategy == "S2":
            lines.append("| S2 | BLOCKED: no genuine historical 1m input | — | — | — | — | — | — | — | — | — |")
            continue
        a, b = rows.loc[strategy], rows.loc[strategy]
        lines.append(
            f"| {strategy} | {fmt(a.net_pnl_full)} | {fmt(a.profit_factor_full)} | {fmt(a.max_drawdown_full)} "
            f"| {int(a.trades_full)} | {a.win_rate_full:.1%} | {fmt(b.net_pnl_oos)} | {fmt(b.profit_factor_oos)} "
            f"| {fmt(b.max_drawdown_oos)} | {int(b.trades_oos)} | {b.win_rate_oos:.1%} |"
        )
    full_bench, oos_bench = full.iloc[0], oos.iloc[0]
    lines.extend([
        "", "## Equal-weight buy-and-hold benchmark", "",
        "| Window | Return | Max drawdown | Max drawdown % | Final equity |",
        "|---|---:|---:|---:|---:|",
        f"| Full 2019–2026 | {full_bench.buy_hold_return:.2%} | {fmt(full_bench.buy_hold_max_drawdown)} | {full_bench.buy_hold_max_drawdown_pct:.2%} | {fmt(full_bench.buy_hold_final_equity)} |",
        f"| OOS 2024–2026 | {oos_bench.buy_hold_return:.2%} | {fmt(oos_bench.buy_hold_max_drawdown)} | {oos_bench.buy_hold_max_drawdown_pct:.2%} | {fmt(oos_bench.buy_hold_final_equity)} |",
        "", "## Cost stress", "",
                  "See round24_cost_stress_full.csv for 5/10/20 bps per-side net P&L, PF, drawdown, trade count and win rate; each cost reruns cash-constrained sizing. round24_oos_metrics.csv contains the same measures for the fixed OOS window.",
                  "",
                  f"Input: {len(status['input_manifest'])} hashed files across {len(status['universe'])} symbols, D1/1H/15m/5m, {status['input_manifest'][0]['first_time_key']} through 2026-10-16. Initial equity: $100,000 per isolated strategy.",
                  "",
                  "Buy-and-hold is equal-dollar, equally weighted across the same six symbols. OOS is 2024-01-01 through 2026-10-16; 2019–2023 is the reference/training period. No parameters were fitted on OOS.",
                  "",
                  "## Data limits", "",
                  "- Source metadata identifies Futu/OpenD, qfq and requested RTH. Provider timezone, exchange calendar, bar closure, provider finality and redistribution rights remain UNKNOWN.",
                  "- Six symbols do not support broader-universe conclusions. No synthetic, interpolated or test-fixture 1m bars were used.",
                  f"- Accounting residual {status['accounting_audit']['max_equity_identity_residual']:.3g}; cash nonnegative={status['accounting_audit']['cash_nonnegative']}; drawdown nonnegative={status['accounting_audit']['drawdown_nonnegative']}.",
                  "- Radar, paper, deployment and trading gates remain disabled.", "",
                  f"Runtime: {status['elapsed_seconds']:.2f}s.", ""])
    (out / "round24_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(capture: Path, out: Path, reference: Path) -> dict:
    started = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    prepared, manifest = _load_capture(capture)
    radar, cache_meta = _load_cached_radar(reference, manifest)
    arms, arm_status = _build_arms(capture, prepared, radar)
    (out / "round24_source_manifest.json").write_text(
        json.dumps({"source": "Futu/OpenD local capture", "files": manifest, "reused_signal_ledgers": cache_meta}, indent=2),
        encoding="utf-8",
    )
    pd.concat([frame.assign(strategy=name) for name, (frame, _) in arms.items() if not frame.empty],
              ignore_index=True).to_csv(out / "round24_signal_ledger.csv", index=False)

    r10.COST_BPS = BASE_SIZING_COST_BPS
    r11.COST_BPS = BASE_SIZING_COST_BPS
    metrics, ledgers, equity_rows, benchmarks = [], [], [], []
    audit = {"max_equity_identity_residual": 0.0, "cash_nonnegative": True, "drawdown_nonnegative": True}
    for strategy, (signals, protocol) in arms.items():
        for window, (start, end) in WINDOWS.items():
            subset = signals[pd.to_datetime(signals.signal_time).between(start, end, inclusive="both")]
            benchmark = _buy_hold(prepared, start, end)
            benchmarks.append({"window": window, **benchmark})
            for cost in COSTS_BPS:
                # Re-size against the scenario's own fees so cash constraints remain valid.
                r11.COST_BPS = cost
                trades = r11._accept_protocol_trades(subset, protocol, prepared)
                gross = pd.to_numeric(trades.get("gross_pnl", pd.Series(dtype=float)), errors="coerce")
                notional = (
                    pd.to_numeric(trades.get("entry_price", pd.Series(dtype=float)), errors="coerce")
                    + pd.to_numeric(trades.get("exit_price", pd.Series(dtype=float)), errors="coerce")
                ) * pd.to_numeric(trades.get("units", pd.Series(dtype=float)), errors="coerce")
                trades["net_pnl"] = gross - notional * cost / 10000.0
                curve = _vectorized_curve(trades, prepared, cost)
                metrics.append(_metric(strategy, window, cost, trades, curve, benchmark))
                audit["max_equity_identity_residual"] = max(
                    audit["max_equity_identity_residual"],
                    float(curve.accounting_residual.abs().max()) if not curve.empty else 0.0,
                )
                audit["cash_nonnegative"] &= bool((curve.cash >= -1e-7).all()) if not curve.empty else True
                audit["drawdown_nonnegative"] &= bool((curve.drawdown >= -1e-7).all()) if not curve.empty else True
                if window in ("full_2019_2026", "oos_2024_2026") and not trades.empty:
                    ledger = trades.copy()
                    ledger["strategy"] = strategy
                    ledger["window"] = window
                    ledger["cost_bps_per_side"] = cost
                    ledger["sizing_cost_bps_per_side"] = cost
                    ledgers.append(ledger)
                if cost == BASE_SIZING_COST_BPS and window in ("full_2019_2026", "oos_2024_2026"):
                    daily = curve.set_index("time_key").resample("D").last().dropna().reset_index()
                    daily["strategy"] = strategy
                    daily["window"] = window
                    daily["cost_bps_per_side"] = cost
                    equity_rows.append(daily)

    metric_df = pd.DataFrame(metrics)
    metric_df.to_csv(out / "round24_strategy_metrics.csv", index=False)
    metric_df[metric_df.window == "full_2019_2026"].to_csv(out / "round24_cost_stress_full.csv", index=False)
    metric_df[metric_df.window == "oos_2024_2026"].to_csv(out / "round24_oos_metrics.csv", index=False)
    pd.DataFrame(benchmarks).drop_duplicates().to_csv(out / "round24_buy_hold_benchmark.csv", index=False)
    if ledgers:
        pd.concat(ledgers, ignore_index=True).to_csv(out / "round24_trade_ledger.csv", index=False)
    if equity_rows:
        pd.concat(equity_rows, ignore_index=True).to_csv(out / "round24_daily_equity_10bps.csv", index=False)

    s2 = [qualify_s2_coverage(capture, symbol) for symbol in SYMBOLS]
    status = {
        "schema_version": "stock-razor-round24-six-strategy-replay-v0.1",
        "status": "PARTIAL_DATA_BLOCKED",
        "source": "Futu/OpenD capture; qfq; requested RTH",
        "universe": list(SYMBOLS), "timeframes_present": list(TIMEFRAMES),
        "timeframe_1m": "NOT_VERIFIED", "arm_status": arm_status, "s2_coverage": s2,
        "input_manifest": manifest, "cached_ledger_validation": cache_meta,
        "costs_bps_per_side": list(COSTS_BPS),
        "base_sizing_cost_bps_per_side": BASE_SIZING_COST_BPS,
        "cost_stress_method": "replay same signals at each per-side fee; scenario-specific cash-constrained fills, sizing, fees, and equity curves",
        "windows": {key: [str(v[0]), str(v[1])] for key, v in WINDOWS.items()},
        "accounting_audit": audit,
        "provenance_limitations": [
            "provider timezone, session calendar, bar closure, provider finality and redistribution rights remain UNKNOWN",
            "six-symbol research only; results do not establish a broader-universe edge",
            "all strategies use the existing 5m execution/stop simulator; S2 requires genuine 1m bars",
            "S3/S4 use SRVP as an entry-confirmation filter; score and sizing overlays were not tested",
        ],
        "safety": {"RADAR_ADMISSION": "BLOCKED", "PAPER_AUTO_READY": "NO",
                   "LIVE_TRADE": "NO", "TRADE_EXECUTION": "NO"},
        "elapsed_seconds": time.perf_counter() - started,
    }
    (out / "round24_status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    _write_report(out, status, metric_df)
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True, help="Round13/Round14 output root containing both subdirectories")
    args = parser.parse_args()
    print(json.dumps(run(args.capture, args.out, args.reference), indent=2))

"""Round14 research-only SRVP confirmation against the frozen Round13 Radar.

SRVP is used only as an entry confirmation: 15m SRVP filters Radar II and 1H
SRVP filters Radar III.  The original profile definition is kept explicit and
causal: prior 100 bars, 21 volume bins, 70% value area, and no future return
selection.  Portfolio acceptance is delegated to the Round13 accounting path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from tools.research import round13_radar_research as r13

LOOKBACK = 100
BINS = 21
VALUE_AREA = 0.70
SYMBOLS = tuple(r13.ROUND10_SYMBOLS)


def _profile(window: pd.DataFrame) -> tuple[float, float, float]:
    low, high = float(window.low.min()), float(window.high.max())
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return (np.nan, np.nan, np.nan)
    edges = np.linspace(low, high, BINS + 1)
    volume = np.zeros(BINS, dtype=float)
    for row in window.itertuples():
        left = max(0, int(np.searchsorted(edges, row.low, side="right") - 1))
        right = min(BINS - 1, int(np.searchsorted(edges, row.high, side="left")))
        volume[left : right + 1] += float(row.volume) / max(1, right - left + 1)
    poc = int(np.argmax(volume))
    selected = {poc}
    target = float(volume.sum() * VALUE_AREA)
    while volume[list(selected)].sum() < target and (min(selected) > 0 or max(selected) < BINS - 1):
        left, right = min(selected) - 1, max(selected) + 1
        left_volume = volume[left] if left >= 0 else -1.0
        right_volume = volume[right] if right < BINS else -1.0
        selected.add(left if left_volume >= right_volume else right)
    return (
        float((edges[poc] + edges[poc + 1]) / 2),
        float(edges[min(selected)]),
        float(edges[max(selected) + 1]),
    )


def _enrich(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.copy()
    values = [_profile(x.iloc[i - LOOKBACK : i]) if i >= LOOKBACK else (np.nan,) * 3 for i in range(len(x))]
    x[["poc", "val", "vah"]] = pd.DataFrame(values, index=x.index)
    x["near_val"] = (x.low <= x.val + (x.vah - x.val) * 0.25) & (x.close > x.val) & (x.close > x.open)
    return x


def _read_capture(capture: Path, symbol: str, timeframe: str) -> pd.DataFrame:
    path = capture / f"US_{symbol}_{timeframe}_qfq_rth_20190101_20261016.csv"
    return r13._read(path)


def _confirmation_times(frames: dict[str, pd.DataFrame], signal_times: pd.Series) -> pd.DataFrame:
    h1 = _enrich(frames["1H"])
    m15 = _enrich(frames["15m"])
    h1_confirmed = h1.loc[h1.near_val, "time_key"]
    m15_confirmed = []
    for row in m15.itertuples():
        prior = h1[h1.time_key < row.time_key]
        ok = False
        if not prior.empty and bool(row.near_val):
            latest = prior.iloc[-1]
            ok = bool(latest.close >= latest.val and latest.close >= latest.poc)
        if ok:
            m15_confirmed.append(row.time_key)
    h1_set, m15_set = set(h1_confirmed), set(m15_confirmed)
    return pd.DataFrame({
        "signal_time": pd.to_datetime(signal_times),
        "srvp_1h_confirm": [t in h1_set for t in pd.to_datetime(signal_times)],
        "srvp_15m_confirm": [t in m15_set for t in pd.to_datetime(signal_times)],
    })


def _metrics(group: pd.DataFrame, curves: pd.DataFrame, protocol: str) -> dict:
    pnl = pd.to_numeric(group.net_pnl, errors="coerce").dropna()
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    curve = curves[curves.protocol == protocol]
    return {
        "protocol": protocol,
        "trades": int(len(group)),
        "net_pnl": float(pnl.sum()),
        "profit_factor": float(wins.sum() / abs(losses.sum())) if not losses.empty else None,
        "total_equity_mdd": float(curve.drawdown.max()) if not curve.empty else 0.0,
        "min_total_equity": float(curve.total_equity.min()) if not curve.empty else None,
    }


def run(capture: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    available = [s for s in SYMBOLS if all((capture / f"US_{s}_{tf}_qfq_rth_20190101_20261016.csv").exists() for tf in ("D1", "1H", "15m", "5m"))]
    cached_ledger = out / "round14_srvp_confirmation_ledger.csv"
    source_manifest = []
    if cached_ledger.exists():
        signal_df = pd.read_csv(cached_ledger)
        for symbol in available:
            source_manifest.extend({"symbol": symbol, "timeframe": tf, "sha256": hashlib.sha256((capture / f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv").read_bytes()).hexdigest()} for tf in ("D1", "1H", "15m", "5m"))
    else:
        signal_frames = []
        for symbol in available:
            frames = {tf: _read_capture(capture, symbol, tf) for tf in ("D1", "1H", "15m", "5m")}
            source_manifest.extend({"symbol": symbol, "timeframe": tf, "sha256": hashlib.sha256((capture / f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv").read_bytes()).hexdigest()} for tf in frames)
            hashes = {tf: hashlib.sha256((capture / f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv").read_bytes()).hexdigest() for tf in frames}
            signals = r13._signals(symbol, {tf: r13._with_regime(r13._indicators(frame)) for tf, frame in frames.items()}, hashes)
            if not signals:
                continue
            signal_df = pd.DataFrame(signals)
            confirms = _confirmation_times(frames, signal_df.signal_time)
            signal_df["srvp_1h_confirm"] = confirms.srvp_1h_confirm.to_numpy()
            signal_df["srvp_15m_confirm"] = confirms.srvp_15m_confirm.to_numpy()
            signal_frames.append(signal_df)
        signal_df = pd.concat(signal_frames, ignore_index=True) if signal_frames else pd.DataFrame()
    prepared = {s: {tf: r13._with_regime(r13._indicators(_read_capture(capture, s, tf))) for tf in ("D1", "1H", "15m", "5m")} for s in available}
    selected = {
        "II": signal_df[(signal_df.protocol == "II") & signal_df.srvp_15m_confirm],
        "III": signal_df[(signal_df.protocol == "III") & signal_df.srvp_1h_confirm],
    }
    all_selected = pd.concat([x.assign(fusion_protocol=k) for k, x in selected.items()], ignore_index=True)
    accepted = {k: r13._accept_protocol_trades(v, k, prepared) for k, v in selected.items()}
    trades = pd.concat(accepted, names=["fusion_protocol", "row"]).reset_index(drop=True)
    trades["fusion_protocol"] = trades["protocol"].map({"II": "IV", "III": "V"})
    curves = pd.concat([r13._portfolio_curve(v, prepared).assign(protocol=k) for k, v in accepted.items()], ignore_index=True)
    signal_df.to_csv(out / "round14_srvp_confirmation_ledger.csv", index=False)
    all_selected.to_csv(out / "round14_fused_signal_ledger.csv", index=False)
    trades.to_csv(out / "round14_fused_trade_ledger.csv", index=False)
    curves.to_csv(out / "round14_fused_equity_curve.csv", index=False)
    metrics = pd.DataFrame([_metrics(accepted[k], curves, k) for k in selected])
    metrics.to_csv(out / "round14_fused_metrics.csv", index=False)
    windows = {"bear_2022": (pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31 23:59:59")), "oos_2024_2026": (pd.Timestamp("2024-01-01"), pd.Timestamp("2026-10-16 23:59:59"))}
    for year in (2023, 2024, 2025):
        windows[f"wf_{year}"] = (pd.Timestamp(f"{year}-01-01"), pd.Timestamp(f"{year}-12-31 23:59:59"))
    window_rows = []
    for protocol, signal_subset in selected.items():
        for window, (start, end) in windows.items():
            subset = signal_subset[pd.to_datetime(signal_subset.signal_time).between(start, end)]
            window_trades = r13._accept_protocol_trades(subset, protocol, prepared)
            window_curve = r13._portfolio_curve(window_trades, prepared).assign(protocol=protocol)
            row = _metrics(window_trades, window_curve, protocol)
            row["window"] = window
            window_rows.append(row)
    pd.DataFrame(window_rows).to_csv(out / "round14_fused_window_metrics.csv", index=False)
    pressure_rows = []
    for protocol, group in accepted.items():
        for cost in (5.0, 10.0, 20.0):
            gross = pd.to_numeric(group.gross_pnl, errors="coerce")
            notional = (pd.to_numeric(group.entry_price, errors="coerce") * pd.to_numeric(group.units, errors="coerce") + pd.to_numeric(group.exit_price, errors="coerce") * pd.to_numeric(group.units, errors="coerce"))
            pressure_rows.append({"protocol": protocol, "fusion_protocol": {"II": "IV", "III": "V"}[protocol], "cost_bps_per_side": cost, "trades": len(group), "gross_pnl": float(gross.sum()), "net_pnl": float((gross - notional * cost / 10000).sum())})
    pd.DataFrame(pressure_rows).to_csv(out / "round14_fused_cost_pressure.csv", index=False)
    status = {
        "schema_version": "stock-razor-round14-srvp-fusion-v0.1",
        "status": "RESEARCH_ONLY",
        "source_manifest": source_manifest,
        "available_symbols": available,
        "fusion_roles": {"IV": "SRVP_15m confirmation + Radar II (D1+1H+15m)", "V": "SRVP_1H confirmation + Radar III (D1+1H)"},
        "srvp_definition": {"lookback_bars": LOOKBACK, "volume_bins": BINS, "value_area": VALUE_AREA, "1h": "near VAL with close > VAL and close > open", "15m": "near VAL plus prior completed 1H close >= VAL and POC"},
        "metrics_sha256": hashlib.sha256((out / "round14_fused_metrics.csv").read_bytes()).hexdigest(),
        "window_metrics_sha256": hashlib.sha256((out / "round14_fused_window_metrics.csv").read_bytes()).hexdigest(),
        "safety": {"RADAR_ADMISSION": "BLOCKED", "PAPER_AUTO_READY": "NO", "LIVE_TRADE": "NO", "TRADE_EXECUTION": "NO"},
    }
    (out / "round14_srvp_fusion_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.capture, args.out), ensure_ascii=False, indent=2))

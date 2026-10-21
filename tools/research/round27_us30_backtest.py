#!/usr/bin/env python
"""Local-only fixed-cohort Round27 US30 backtest orchestrator."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.research import round10_radar_replay as r10
from tools.research import round11_radar_research as r11
from tools.research import round13_radar_research as r13
from tools.research import round14_srvp_fusion as r14
from tools.research import round24_six_strategy_backtest as r24
from tools.research import round26_s2_candidate_replay as r26
from tools.research.round16_research import SECTOR as R16_SECTOR

TFS = ("D1", "1H", "15m", "5m", "1m")
BASE_TFS = TFS
ARMS = ("S1", "S2_CANDIDATE", "S3", "S4", "S5", "S6")
LEGACY = {"AAPL", "AMD", "COHR", "NVDA", "QQQ", "TSLA"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def locate(symbol: str, tf: str, fresh: Path, legacy_high: Path, legacy_1m: Path) -> Path:
    name = f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv"
    candidate = fresh / name
    if candidate.is_file():
        return candidate
    quarantine = fresh / "quarantine" / name
    if quarantine.is_file():
        return quarantine
    if symbol in LEGACY:
        path = (legacy_1m if tf == "1m" else legacy_high) / name
        if path.is_file():
            return path
    raise FileNotFoundError(f"missing Round27 input {symbol}/{tf}: {name}")


def link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if digest(src) == digest(dst):
            return
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    if digest(src) != digest(dst):
        raise IOError(f"staged input hash mismatch: {src}")


def stage(symbols: list[str], fresh: Path, legacy_high: Path, legacy_1m: Path,
          raw_root: Path, effective_root: Path) -> tuple[list[dict], dict[str, list[str]], list[dict]]:
    sources = []
    for symbol in symbols:
        for tf in TFS:
            src = locate(symbol, tf, fresh, legacy_high, legacy_1m)
            raw = raw_root / src.name
            link_or_copy(src, raw)
            sources.append((symbol, tf, src, raw))
    bad_rows = []
    excluded_dates: dict[str, set[str]] = {symbol: set() for symbol in symbols}
    for symbol, tf, src, raw in sources:
        frame = pd.read_csv(raw)
        frame["time_key"] = pd.to_datetime(frame.time_key, errors="raise")
        numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="raise")
        invalid = (~np.isfinite(numeric.to_numpy(dtype=float)).all(axis=1)
                   | (numeric[["open", "high", "low", "close"]] <= 0).any(axis=1).to_numpy()
                   | (numeric.volume < 0).to_numpy()
                   | (numeric.high < numeric[["open", "close", "low"]].max(axis=1)).to_numpy()
                   | (numeric.low > numeric[["open", "close", "high"]].min(axis=1)).to_numpy())
        if invalid.any():
            for idx in np.flatnonzero(invalid):
                row = frame.iloc[int(idx)]
                day = row.time_key.strftime("%Y-%m-%d")
                excluded_dates[symbol].add(day)
                bad_rows.append({"symbol": symbol, "timeframe": tf, "session": day,
                                 "time_key": row.time_key.isoformat(),
                                 "open": float(row.open), "high": float(row.high),
                                 "low": float(row.low), "close": float(row.close),
                                 "volume": float(row.volume), "source_path": str(src)})
    exclusions = {symbol: sorted(days) for symbol, days in excluded_dates.items() if days}
    rows = []
    for symbol, tf, src, raw in sources:
        effective = effective_root / src.name
        days = set(exclusions.get(symbol, []))
        if days:
            frame = pd.read_csv(raw)
            day = pd.to_datetime(frame.time_key, errors="raise").dt.strftime("%Y-%m-%d")
            keep = ~day.isin(days)
            excluded_count = int((~keep).sum())
            effective.parent.mkdir(parents=True, exist_ok=True)
            tmp = effective.with_suffix(".csv.tmp")
            frame.loc[keep].to_csv(tmp, index=False)
            tmp.replace(effective)
            effective_rows = int(keep.sum())
        else:
            link_or_copy(raw, effective)
            excluded_count = 0
            effective_rows = sum(1 for _ in raw.open("rb")) - 1
        rows.append({
            "symbol": symbol, "timeframe": tf, "source_path": str(src),
            "source_sha256": digest(src), "raw_staged_path": str(raw),
            "raw_staged_sha256": digest(raw), "effective_path": str(effective),
            "effective_sha256": digest(effective), "effective_rows": effective_rows,
            "excluded_sessions": sorted(days), "excluded_session_rows": excluded_count,
        })
    return rows, exclusions, bad_rows


def configure(symbols: list[str], sectors: dict[str, str]) -> None:
    r10.SYMBOLS = tuple(symbols)
    r10.SECTOR.clear()
    r10.SECTOR.update(sectors)
    r11.ROUND10_SYMBOLS = r11.SYMBOLS = tuple(symbols)
    r13.ROUND10_SYMBOLS = r13.SYMBOLS = tuple(symbols)
    r14.SYMBOLS = r24.SYMBOLS = r26.SYMBOLS = tuple(symbols)
    r26.SECTOR.clear()
    r26.SECTOR.update(sectors)
    R16_SECTOR.clear()
    R16_SECTOR.update(sectors)


def _confirmation_flags_at_signals(frames: dict[str, pd.DataFrame], signal_times: pd.Series) -> dict[str, list[bool]]:
    """Evaluate Round14's prior-bar SRVP rule only at actual signal times."""
    h1 = frames["1H"].reset_index(drop=True)
    m15 = frames["15m"].reset_index(drop=True)
    h1_times = pd.to_datetime(h1.time_key)
    m15_times = pd.to_datetime(m15.time_key)
    h1_lookup = {pd.Timestamp(ts): i for i, ts in enumerate(h1_times)}
    m15_lookup = {pd.Timestamp(ts): i for i, ts in enumerate(m15_times)}
    h1_cache: dict[int, tuple[float, float, float]] = {}
    m15_cache: dict[int, tuple[float, float, float]] = {}
    def profile_at(frame: pd.DataFrame, index: int, cache: dict[int, tuple[float, float, float]]) -> tuple[float, float, float]:
        if index < r14.LOOKBACK:
            return (float("nan"),) * 3
        if index not in cache:
            cache[index] = r14._profile(frame.iloc[index-r14.LOOKBACK:index])
        return cache[index]
    def near_val(frame: pd.DataFrame, index: int, cache: dict[int, tuple[float, float, float]]) -> bool:
        poc, val, vah = profile_at(frame, index, cache)
        if not np.isfinite([poc, val, vah]).all():
            return False
        row = frame.iloc[index]
        return bool(row.low <= val + (vah-val)*0.25 and row.close > val and row.close > row.open)
    one_hour, fifteen = [], []
    for value in pd.to_datetime(signal_times):
        ts = pd.Timestamp(value)
        i1 = h1_lookup.get(ts)
        i15 = m15_lookup.get(ts)
        one_hour.append(False if i1 is None else near_val(h1, i1, h1_cache))
        confirmed15 = False
        if i15 is not None and near_val(m15, i15, m15_cache):
            prior = int(h1_times.searchsorted(ts, side="left")) - 1
            if prior >= 0:
                poc, val, _ = profile_at(h1, prior, h1_cache)
                latest = h1.iloc[prior]
                confirmed15 = bool(np.isfinite([poc, val]).all() and latest.close >= val and latest.close >= poc)
        fifteen.append(confirmed15)
    return {"srvp_1h_confirm": one_hour, "srvp_15m_confirm": fifteen}

def build_signal_cache(capture: Path, out: Path, symbols: list[str]) -> list[dict]:
    """Build only the Round13/14 signal cache required by Round24; skip redundant legacy P&L curves."""
    baseline = out / "round13_baseline"
    fusion = out / "round14_fusion"
    baseline.mkdir(parents=True, exist_ok=True)
    fusion.mkdir(parents=True, exist_ok=True)
    source_manifest = []
    radar_frames = []
    for symbol in symbols:
        frames = {tf: r13._read(capture / f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv")
                  for tf in ("D1", "1H", "15m", "5m")}
        hashes = {}
        for tf in frames:
            path = capture / f"US_{symbol}_{tf}_qfq_rth_20190101_20261016.csv"
            hashes[tf] = digest(path)
            source_manifest.append({"symbol": symbol, "timeframe": tf, "sha256": hashes[tf]})
        featured = {tf: r13._with_regime(r13._indicators(frame)) for tf, frame in frames.items()}
        signals = r13._signals(symbol, featured, hashes)
        if signals:
            frame = pd.DataFrame(signals)
            frame["market_regime"] = [r13._regime(featured["D1"], featured["1H"], pd.Timestamp(ts))
                                       for ts in frame.signal_time]
            confirms = _confirmation_flags_at_signals(frames, frame.signal_time)
            frame["srvp_1h_confirm"] = confirms["srvp_1h_confirm"]
            frame["srvp_15m_confirm"] = confirms["srvp_15m_confirm"]
            radar_frames.append(frame)
    radar = pd.concat(radar_frames, ignore_index=True) if radar_frames else pd.DataFrame()
    radar.drop(columns=["srvp_1h_confirm", "srvp_15m_confirm"], errors="ignore").to_csv(baseline / "round13_signal_ledger.csv", index=False)
    radar.to_csv(fusion / "round14_srvp_confirmation_ledger.csv", index=False)
    (baseline / "round13_status.json").write_text(json.dumps({"status": "SIGNALS_ONLY_FOR_ROUND24", "source_manifest": source_manifest}, indent=2), encoding="utf-8")
    (fusion / "round14_srvp_fusion_status.json").write_text(json.dumps({"status": "CONFIRMATIONS_ONLY_FOR_ROUND24", "source_manifest": source_manifest}, indent=2), encoding="utf-8")
    return source_manifest

def strict_data_quality_audit(out: Path, exclusions: dict[str, list[str]], findings: list[dict]) -> None:
    if not findings:
        raise RuntimeError("input audit found no invalid OHLCV rows; expected known COHR defect was not reproduced")
    atomic_json(out / "strict_full_data_blocked.json", {
        "status": "EXPECTED_BLOCK", "invalid_rows": len(findings),
        "full_sessions_excluded": exclusions, "findings": findings,
        "policy": "preserve raw captures; remove each affected symbol's complete session across every timeframe, strategy and matched benchmark",
    })
    lines = ["Strict raw-input validation: EXPECTED_BLOCK",
             f"Invalid OHLCV rows: {len(findings)}",
             f"Full-session exclusions: {json.dumps(exclusions, ensure_ascii=False, sort_keys=True)}"]
    lines.extend(f"{x['symbol']} {x['timeframe']} {x['time_key']}: O={x['open']} H={x['high']} L={x['low']} C={x['close']} V={x['volume']}" for x in findings)
    (out / "strict_full_data_blocked.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def combine(base_path: Path, candidate_path: Path) -> pd.DataFrame:
    base = pd.read_csv(base_path)
    candidate = pd.read_csv(candidate_path)
    candidate = candidate[candidate.strategy == "S2_CANDIDATE"].copy()
    source = pd.concat([base, candidate], ignore_index=True, sort=False)
    source = source[source.strategy.isin(ARMS)].copy()
    rows = []
    for window in ("full_2019_2026", "train_2019_2023", "oos_2024_2026"):
        for cost in (5.0, 10.0, 20.0):
            g = source[(source.window == window) & (source.cost_bps_per_side == cost)]
            if g.empty:
                raise ValueError(f"missing metrics {window}/{cost}")
            bhs = g.buy_hold_return.dropna().to_numpy(dtype=float)
            if len(bhs) == 0 or not np.allclose(bhs, bhs[0], rtol=0, atol=1e-9):
                raise ValueError(f"buy-and-hold mismatch in {window}/{cost}")
            bh, bhdd = float(bhs[0]), float(g.buy_hold_max_drawdown_pct.dropna().iloc[0])
            for strategy in ARMS:
                match = g[g.strategy == strategy]
                if match.empty:
                    rows.append({"strategy": strategy, "window": window, "cost_bps_per_side": cost,
                                 "status": "OFFICIAL_S2_RULE_NOT_FOUND" if strategy == "S2_CANDIDATE" else "NOT_COMPUTED"})
                    continue
                x = match.iloc[0]
                rows.append({"strategy": strategy, "window": window, "cost_bps_per_side": cost,
                             "status": "CANDIDATE_UNVALIDATED" if strategy == "S2_CANDIDATE" else "ROUND24_METHOD_30_SYMBOL",
                             "net_pnl": x.net_pnl, "profit_factor": x.profit_factor,
                             "max_drawdown": x.max_drawdown, "max_drawdown_pct": x.max_drawdown_pct,
                             "trades": x.trades, "win_rate": x.win_rate,
                             "buy_hold_return": bh, "buy_hold_max_drawdown_pct": bhdd})
            x = g.iloc[0]
            rows.append({"strategy": "BUY_HOLD_EQUAL_WEIGHT", "window": window,
                         "cost_bps_per_side": cost, "status": "30_SYMBOL_MATCHED_BENCHMARK",
                         "net_pnl": 100000.0 * bh, "profit_factor": None,
                         "max_drawdown": x.buy_hold_max_drawdown, "max_drawdown_pct": bhdd,
                         "trades": None, "win_rate": None,
                         "buy_hold_return": bh, "buy_hold_max_drawdown_pct": bhdd})
    return pd.DataFrame(rows)


def report(out: Path, symbols: list[str], combined: pd.DataFrame, exclusions: dict[str, list[str]]) -> None:
    full = combined[(combined.window == "full_2019_2026") & (combined.cost_bps_per_side == 10)]
    oos = combined[(combined.window == "oos_2024_2026") & (combined.cost_bps_per_side == 10)]
    fmt = lambda v: "—" if pd.isna(v) else f"{float(v):,.2f}"
    lines = [
        "# Round27 US30 fixed-cohort six-arm research replay", "",
        "Status: EXPLORATORY_FIXED_SURVIVOR_COHORT. Point-in-time membership is unresolved; these are conditional research results, not general 30-stock performance claims or strategy promotion.", "",
        f"Universe: {len(symbols)} frozen symbols selected as of 2026-10-20; local Futu/OpenD QFQ/RTH, requested 2019-01-01 through 2026-10-16. Raw captures remain outside Git.", "",
        "Official S2 history was not recovered. S2 is the Round26 candidate only. Data-quality audit found invalid OHLCV bars; every affected full symbol session was removed consistently across all timeframes, strategy arms and the matched buy-and-hold baseline. Raw captures remain immutable; see strict_full_data_blocked.json.", "",
        f"Full-session exclusions: {json.dumps(exclusions, ensure_ascii=False, sort_keys=True)}.", "",
        "## 10 bps per side", "",
        "|Strategy|Window|Net P&L|PF|Max DD|Max DD %|Trades|Win rate|B&H return|B&H max DD|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, frame in (("Full", full), ("OOS", oos)):
        for strategy in ("S1", "S2_CANDIDATE", "S3", "S4", "S5", "S6", "BUY_HOLD_EQUAL_WEIGHT"):
            m = frame[frame.strategy == strategy]
            if m.empty:
                continue
            x = m.iloc[0]
            lines.append(f"|{strategy}|{name}|{fmt(x.get('net_pnl'))}|{fmt(x.get('profit_factor'))}|{fmt(x.get('max_drawdown'))}|{fmt(x.get('max_drawdown_pct'))}|{fmt(x.get('trades'))}|{fmt(x.get('win_rate'))}|{fmt(x.get('buy_hold_return'))}|{fmt(x.get('buy_hold_max_drawdown_pct'))}|")
    lines += [
        "", "All 5/10/20 bps per-side costs and training/OOS windows are in round27_six_strategy_comparison_all_costs.csv. Detailed ledgers and audit outputs are in round24_six_strategy and round26_s2_candidate.", "",
        "The 30 names are a fixed survivor cohort, not point-in-time constituents. Provider finality, timestamp semantics, corporate-action point-in-time handling and independent quality signoff remain unresolved.", "",
        "TRADE_EXECUTION=NO; RADAR_ADMISSION=BLOCKED; PAPER_AUTO_READY=NO; LIVE_TRADE=NO.", "",
    ]
    (out / "round27_us30_backtest_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config_path: Path, fresh: Path, legacy_high: Path, legacy_1m: Path,
        raw: Path, effective: Path, out: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    items = config["markets"]["us"]["symbols"]
    symbols = [x["symbol"] for x in items]
    sectors = {x["symbol"]: x["sector"] for x in items}
    if len(symbols) != 30 or len(set(symbols)) != 30:
        raise ValueError("Round27 config must contain 30 unique symbols")
    if config["membership_controls"]["point_in_time_membership"] != "UNRESOLVED":
        raise ValueError("unexpected membership state")
    out.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    if effective.exists():
        shutil.rmtree(effective)
    inputs, exclusions, findings = stage(symbols, fresh, legacy_high, legacy_1m, raw, effective)
    if len(inputs) != 150 or any(x["source_sha256"] != x["raw_staged_sha256"] for x in inputs):
        raise ValueError("incomplete or changed raw input staging")
    atomic_json(out / "round27_input_manifest.json", {
        "schema": "stock-razor-round27-input-manifest-v1",
        "config_sha256": digest(config_path), "source": "local Futu/OpenD QFQ/RTH",
        "full_session_exclusions": exclusions, "invalid_ohlcv_rows": len(findings),
        "files": inputs,
    })
    strict_data_quality_audit(out, exclusions, findings)
    configure(symbols, sectors)
    cache_manifest = build_signal_cache(effective, out, symbols)
    s13 = {"status": "SIGNALS_ONLY_FOR_ROUND24", "source_manifest": cache_manifest}
    s14 = {"status": "CONFIRMATIONS_ONLY_FOR_ROUND24", "source_manifest": cache_manifest}
    s24 = r24.run(effective, out / "round24_six_strategy", out)
    baseline = out / "round24_six_strategy" / "round24_strategy_metrics.csv"
    r26.run(effective, out / "round26_s2_candidate", "America/New_York", "end",
            exclude_invalid_session=None,
            baseline_metrics=baseline, one_minute_capture=effective)
    candidate_status_path = out / "round26_s2_candidate" / "s2_candidate_status.json"
    candidate_status = json.loads(candidate_status_path.read_text(encoding="utf-8"))
    candidate_status["full_session_exclusions"] = exclusions
    candidate_status["invalid_ohlcv_rows_removed_in_derived_capture"] = len(findings)
    candidate_status["raw_capture_repaired"] = False
    atomic_json(candidate_status_path, candidate_status)
    candidate_report_path = out / "round26_s2_candidate" / "s2_candidate_report.md"
    if candidate_report_path.exists():
        with candidate_report_path.open("a", encoding="utf-8") as stream:
            stream.write("\n\nRound27 data-quality sensitivity: raw capture was preserved; affected full sessions were excluded across all timeframes. Exclusions: " +
                         json.dumps(exclusions, ensure_ascii=False, sort_keys=True) + ".\n")
    combined = combine(baseline, out / "round26_s2_candidate" / "s2_candidate_metrics.csv")
    path = out / "round27_six_strategy_comparison_all_costs.csv"
    combined.to_csv(path, index=False)
    report(out, symbols, combined, exclusions)
    status = {
        "schema": "stock-razor-round27-us30-backtest-v1",
        "state": "EXPLORATORY_FIXED_SURVIVOR_COHORT",
        "symbols": symbols, "symbol_count": 30,
        "membership_controls": config["membership_controls"],
        "source": "local Futu/OpenD QFQ/RTH", "input_files": len(inputs),
        "full_sessions_excluded": exclusions,
        "invalid_ohlcv_rows": len(findings),
        "round13_status": s13.get("status"), "round14_status": s14.get("status"),
        "round24_status": s24.get("status"), "s2_candidate_status": "BACKTEST_COMPUTED_NOT_VALIDATED",
        "comparison": str(path),
        "unresolved": ["point_in_time_membership", "survivorship_bias", "bar_timestamp_semantics",
                       "provider_finality", "independent_data_quality_signoff"],
        "safety": {"TRADE_EXECUTION": "NO", "RADAR_ADMISSION": "BLOCKED",
                   "PAPER_AUTO_READY": "NO", "LIVE_TRADE": "NO"},
    }
    atomic_json(out / "round27_us30_backtest_status.json", status)
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", type=Path, required=True)
    ap.add_argument("--capture-root", type=Path, required=True)
    ap.add_argument("--legacy-high-capture", type=Path, required=True)
    ap.add_argument("--legacy-one-minute-capture", type=Path, required=True)
    ap.add_argument("--raw-root", type=Path, required=True)
    ap.add_argument("--effective-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    status = run(a.config, a.capture_root, a.legacy_high_capture, a.legacy_one_minute_capture,
                 a.raw_root, a.effective_root, a.out)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline B/C/D/E replay on explicitly hash-pinned inputs; A stays blocked.

No fetches, broker calls, imputation, optimization or new service credentials.
Each window resets cash and liquidates its own boundary. Prior history is used
only to warm features. A missing raw path blocks the run, never drops a ticker.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.services.strategy_lab.s3_mtf import Rules, build_signals, metrics, prepare_replay, replay, validate_input


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_bars(item, root):
    path = root / item["path"]
    if digest(path) != item["sha256"]:
        raise ValueError("INPUT_HASH_MISMATCH")
    if item["label"] not in {"start", "end"} or not item["source"] or not item["price_basis"]:
        raise ValueError("UNSPECIFIED_SOURCE_LABEL_OR_PRICE_BASIS")
    x = pd.read_csv(path)
    values = [pd.Timestamp(v) for v in x[item["timestamp_column"]]]
    aware = [v.tzinfo is not None for v in values]
    if all(aware):
        ts = pd.DatetimeIndex(pd.to_datetime(values, utc=True))
    elif not any(aware):
        ts = pd.DatetimeIndex(values).tz_localize(item["timezone"], ambiguous="raise", nonexistent="raise").tz_convert("UTC")
    else:
        raise ValueError("MIXED_NAIVE_AND_AWARE_SOURCE_LABELS")
    x["end"] = ts + pd.Timedelta(minutes=5 if item["label"] == "start" else 0)
    return x


def benchmark(bars, initial, cost_bps):
    rate = cost_bps / 10000
    units = initial / (bars.open.iloc[0]*(1+rate))
    curve = pd.DataFrame(dict(end=bars.end, equity=units*bars.close,
                              cash=0., gross_exposure=1.))
    curve.loc[curve.index[-1], "equity"] *= 1-rate
    trades = pd.DataFrame([dict(entry_at=bars.end.iloc[0]-pd.Timedelta(minutes=5),
                                exit_at=bars.end.iloc[-1],
                                net_pnl=curve.equity.iloc[-1]-initial)])
    return metrics(trades, curve, initial), curve


def select_window(schedule, start, end):
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("WINDOW_REQUIRES_AWARE_ORDERED_TIMESTAMPS")
    overlap = schedule[(schedule.open_at < end) & (schedule.close_at > start)]
    if overlap.empty:
        raise ValueError("EMPTY_WINDOW")
    if ((overlap.open_at < start) | (overlap.close_at > end)).any():
        raise ValueError("PARTIAL_SESSION_WINDOW_REJECTED")
    return overlap.reset_index(drop=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("REFUSE_TO_OVERWRITE_OUTPUT")
    manifest = json.loads(args.manifest.read_text())
    root = args.manifest.resolve().parent
    rules = Rules(**manifest.get("rules", {}))
    items = manifest["symbols"]
    if not items or len({r["symbol"] for r in items}) != len(items):
        raise ValueError("EMPTY_OR_DUPLICATE_UNIVERSE")
    receipt = dict(status="BLOCKED", matrix_complete=False, A="BLOCKED_NO_FROZEN_D1_H1_M15_RULE",
                   manifest_sha256=digest(args.manifest), rules=asdict(rules),
                   source_sha256=digest(Path(__file__).resolve().parents[1]/"src/services/strategy_lab/s3_mtf.py"),
                   history_reused=manifest["history_reused"],
                   untouched_oos="NOT_ESTABLISHED", TRADE_EXECUTION="NO", promotion="NO")
    missing = [r["path"] for r in [manifest["schedule"], *items, manifest["benchmark"]]
               if not (root/r["path"]).is_file()]
    receipt["missing_inputs"] = missing
    args.output.mkdir(parents=True)
    if missing or args.preflight_only:
        receipt["reason"] = "RAW_INPUTS_MISSING" if missing else "PREFLIGHT_ONLY_NOT_BACKTESTED"
        (args.output/"status.json").write_text(json.dumps(receipt, indent=2))
        print(json.dumps(receipt, indent=2))
        return
    schedule_path = root/manifest["schedule"]["path"]
    if digest(schedule_path) != manifest["schedule"]["sha256"]:
        raise ValueError("SCHEDULE_HASH_MISMATCH")
    schedule = pd.read_csv(schedule_path)
    for k in ("open_at", "close_at"):
        if any(pd.Timestamp(x).tzinfo is None for x in schedule[k]):
            raise ValueError("SCHEDULE_EXPLICIT_OFFSETS_REQUIRED")
        schedule[k] = pd.to_datetime(schedule[k], utc=True)
    source = {r["symbol"]:load_bars(r, root) for r in items}
    sectors = {r["symbol"]:r["sector"] for r in items}
    for x in source.values():
        validate_input(x, schedule)
    prepared = prepare_replay(source, schedule)
    qqq = load_bars(manifest["benchmark"], root)
    validate_input(qqq, schedule)
    if manifest["benchmark"]["symbol"] != "QQQ":
        raise ValueError("QQQ_BENCHMARK_REQUIRED")
    all_signals = {arm:{sym:build_signals(x, schedule, arm, rules, prepared=prepared, symbol=sym) for sym,x in source.items()}
                   for arm in ("B", "C", "D", "E")}
    results = []
    for window in manifest["windows"]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", window["name"]):
            raise ValueError("INVALID_WINDOW_NAME")
        start, end = pd.Timestamp(window["start"]), pd.Timestamp(window["end"])
        ss = select_window(schedule, start, end)
        if int(schedule.close_at.searchsorted(ss.open_at.iloc[0])) < 200:
            raise ValueError("COMMON_200_SESSION_WARMUP_REQUIRED_BEFORE_TEST_WINDOW")
        qb = qqq[(qqq.end>ss.open_at.iloc[0]) & (qqq.end<=ss.close_at.iloc[-1])].reset_index(drop=True)
        for cost in (0., 5., 10., 20.):
            for arm in ("B", "C", "D", "E"):
                sig = {sym:x[(x.decision_at>=ss.open_at.iloc[0]) & (x.decision_at<=ss.close_at.iloc[-1])]
                       if not x.empty else x for sym,x in all_signals[arm].items()}
                t,e,c = replay(source, schedule, sig, sectors, rules=rules, cost_bps=cost,
                               trade_start=ss.open_at.iloc[0], trade_end=ss.close_at.iloc[-1], prepared=prepared)
                name = f"{window['name']}_{arm}_{int(cost)}bps"
                t.to_csv(args.output/f"{name}_trades.csv", index=False)
                e.to_csv(args.output/f"{name}_events.csv", index=False)
                c.to_csv(args.output/f"{name}_equity.csv", index=False)
                results.append(dict(window=window["name"], actual_start=ss.open_at.iloc[0].isoformat(),
                                    actual_end=ss.close_at.iloc[-1].isoformat(), arm=arm, cost_bps=cost, **metrics(t,c)))
            qm,qc = benchmark(qb, 100000., cost)
            results.append(dict(window=window["name"], actual_start=ss.open_at.iloc[0].isoformat(),
                                actual_end=ss.close_at.iloc[-1].isoformat(), arm="QQQ_BH", cost_bps=cost, **qm))
            qc.to_csv(args.output/f"{window['name']}_QQQ_BH_{int(cost)}bps_equity.csv", index=False)
    pd.DataFrame(results).to_csv(args.output/"metrics.csv", index=False)
    receipt.update(status="PARTIAL_MATRIX_REPLAYED_RESEARCH_ONLY", reason="A_AND_UNTOUCHED_OOS_MISSING")
    (args.output/"status.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()

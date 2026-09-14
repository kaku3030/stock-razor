#!/usr/bin/env python3
"""Compute research-only cross-sectional relative-strength rankings."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _series(path: Path) -> tuple[str, list[tuple[str, float]]]:
    with path.open(encoding="utf-8") as handle:
        rows = [(row["date"], float(row["close"])) for row in csv.DictReader(handle)]
    return path.stem, rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lookbacks", default="20,60")
    args = parser.parse_args()
    lookbacks = tuple(int(value) for value in args.lookbacks.split(","))
    rankings = {}
    for path in sorted(args.input_dir.glob("*.csv")):
        # Cross-source mirror captures live beside the primary universe for
        # artifact atomicity; they must never become extra securities.
        if path.stem.endswith("_akshare"):
            continue
        symbol, rows = _series(path)
        if not rows:
            continue
        values = {"symbol": symbol, "as_of": rows[-1][0], "observations": len(rows)}
        for lookback in lookbacks:
            values[f"return_{lookback}d"] = (rows[-1][1] / rows[-1 - lookback][1] - 1.0) if len(rows) > lookback else None
        rankings[symbol] = values
    result = {"schema": "radar-cross-sectional-rs-v0.1", "lookbacks": lookbacks,
              "rankings": {str(lookback): sorted((item for item in rankings.values() if item[f"return_{lookback}d"] is not None), key=lambda item: item[f"return_{lookback}d"], reverse=True) for lookback in lookbacks}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "COMPUTED", "symbols": len(rankings), "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

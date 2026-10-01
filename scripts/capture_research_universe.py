#!/usr/bin/env python3
"""Capture a frozen research universe with per-symbol provenance."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for market, definition in config["markets"].items():
        for symbol in definition["symbols"]:
            safe_symbol = symbol.replace(".", "_")
            output = args.output_dir / f"{market}_{safe_symbol}.csv"
            command = [sys.executable, "scripts/capture_research_eod.py", "--market", market,
                       "--symbol", symbol, "--start", args.start, "--end", args.end,
                       "--output", str(output), "--retries", "3"]
            result = subprocess.run(command, check=False)
            summary.append({"market": market, "symbol": symbol, "exit_code": result.returncode,
                            "status": "CAPTURED" if result.returncode == 0 else "BLOCKED"})
    print(json.dumps({"schema": "radar-research-universe-capture-v0.1", "summary": summary}, sort_keys=True))
    return 0 if all(item["exit_code"] == 0 for item in summary) else 2


if __name__ == "__main__":
    raise SystemExit(main())

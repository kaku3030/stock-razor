"""Create reproducible, fail-closed offline Vibe-Trading data audit reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.strategy_lab.data_audit import audit_csv


def render_markdown(report: dict) -> str:
    lines = [
        "# Vibe-Trading V0.5 offline data audit",
        "",
        f"- Status: `{report['status']}`",
        f"- Historical replay eligibility: `{report['historical_replay']['eligibility']}`",
        f"- Symbol: `{report['symbol']}`; rows: `{report['rows']}`",
        f"- Source file SHA-256: `{report['hashes']['source_file']}`",
        f"- Rows SHA-256: `{report['hashes']['rows']}`",
        "",
        "| Check | Result |",
        "|---|---|",
    ]
    for key, value in report["checks"].items():
        if isinstance(value, list):
            value = ", ".join(map(str, value)) or "none"
        lines.append(f"| {key} | `{value}` |")
    lines += [
        "",
        "Freshness is reported separately from historical replay eligibility; no UNKNOWN or NOT_VERIFIED value is promoted to PASS.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--write-json", type=Path)
    parser.add_argument("--write-md", type=Path)
    args = parser.parse_args()
    report = audit_csv(args.csv)
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.write_json:
        args.write_json.parent.mkdir(parents=True, exist_ok=True)
        args.write_json.write_text(payload, encoding="utf-8")
    if args.write_md:
        args.write_md.parent.mkdir(parents=True, exist_ok=True)
        args.write_md.write_text(render_markdown(report), encoding="utf-8")
    if not args.write_json and not args.write_md:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

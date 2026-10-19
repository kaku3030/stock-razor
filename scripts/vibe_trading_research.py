"""Minimal natural-language, research-only entry for Strategy Lab replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.strategy_lab.vibe_replay import load_fixture, replay_csv_files, replay_fixture

PROFILES = {"b0": "vibe-b0-research-only", "v0.2": "vibe-v0.2-research-only", "strong_pullback": "vibe-strong-pullback-research-only"}


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Vibe-Trading research replay",
        "",
        f"- Status: `{result['status']}`",
        f"- Execution: `{result['execution']}`",
        f"- Input kind: `{result.get('replay', {}).get('input_kind', 'CSV_RESEARCH')}`",
        f"- Data audit: `{result.get('replay', {}).get('data_audit', {}).get('status', 'NOT_VERIFIED')}`",
        f"- OOS: `{result.get('oos', 'NOT_VERIFIED')}`",
        f"- Radar admission: `{result['radar_admission']}`",
        "",
    ]
    replay = result.get("replay")
    if isinstance(replay, dict):
        lines.append("| Symbol | Rows | Audit |")
        lines.append("|---|---:|---|")
        for item in replay.get("inputs", []):
            audit = item.get("data_audit", {})
            lines.append(
                f"| {item.get('symbol', 'UNKNOWN')} | {item.get('rows', 0)} | "
                f"`{audit.get('historical_replay', {}).get('eligibility', 'NOT_VERIFIED')}` |"
            )
        lines += [
            "",
            "Metrics are research-only. Missing or unverified provenance, timezone/DST, calendar, bar closure, provider finality, or sample requirements block OOS claims.",
        ]
    else:
        lines.append("No replay was executed; this is a request description only.")
    return "\n".join(lines) + "\n"


def parse_request(prompt: str) -> dict[str, Any]:
    text = prompt.casefold()
    matches = []
    if re.search(r"\bb0\b", text):
        matches.append("b0")
    if re.search(r"\bv0\.2\b|vibe.?trading", text):
        matches.append("v0.2")
    if "strong pullback" in text or "strong_pullback" in text:
        matches.append("strong_pullback")
    profiles = tuple(dict.fromkeys(matches))
    if len(profiles) != 1:
        raise ValueError("request must name exactly one supported profile: B0, V0.2, or Strong Pullback")
    profile = profiles[0]
    return {"schema_version": "stock-razor-vibe-research-request-v0.1", "status": "RESEARCH_ONLY", "profile": profile, "replay_engine": "src.services.strategy_lab.vibe_replay.replay_fixture", "rule_version": PROFILES[profile], "execution": "NOT_RUN", "oos": "NOT_VERIFIED", "radar_admission": "BLOCKED", "trade_execution": "NO", "prompt": prompt}


def parse_comparison_request(prompt: str) -> dict[str, Any]:
    text = prompt.casefold()
    profiles = []
    if re.search(r"\bb0\b", text):
        profiles.append("b0")
    if re.search(r"\bv0\.2\b|vibe.?trading", text):
        profiles.append("v0.2")
    if "strong pullback" in text or "strong_pullback" in text:
        profiles.append("strong_pullback")
    profiles = tuple(dict.fromkeys(profiles))
    if len(profiles) < 2:
        raise ValueError("comparison request must name at least two supported profiles")
    return {"schema_version": "stock-razor-vibe-research-request-v0.2", "status": "RESEARCH_ONLY", "profiles": profiles, "execution": "NOT_RUN", "oos": "NOT_VERIFIED", "radar_admission": "BLOCKED", "trade_execution": "NO", "prompt": prompt}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--csv", type=Path, action="append")
    parser.add_argument("--write", type=Path)
    parser.add_argument("--write-md", type=Path)
    args = parser.parse_args()
    result = parse_comparison_request(args.prompt) if "compare" in args.prompt.casefold() else parse_request(args.prompt)
    if args.fixture and args.csv:
        parser.error("--fixture and --csv cannot be combined")
    if args.csv:
        strategies = result["profiles"] if "profiles" in result else (result["profile"],)
        result = {**result, "replay": replay_csv_files(args.csv, strategies), "execution": "REPLAY_COMPLETED"}
        report_basis = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        result["report_sha256"] = hashlib.sha256(report_basis).hexdigest()
    elif args.fixture:
        fixture, bars = load_fixture(str(args.fixture))
        strategies = result["profiles"] if "profiles" in result else (result["profile"],)
        result = {**result, "replay": replay_fixture(fixture, bars, strategies), "execution": "REPLAY_COMPLETED"}
        report_basis = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        result["report_sha256"] = hashlib.sha256(report_basis).hexdigest()
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(payload, encoding="utf-8")
    if args.write_md:
        args.write_md.parent.mkdir(parents=True, exist_ok=True)
        args.write_md.write_text(render_markdown(result), encoding="utf-8")
    if not args.write:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

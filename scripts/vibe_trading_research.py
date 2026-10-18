"""Minimal natural-language, research-only entry for Strategy Lab replay."""

from __future__ import annotations

import argparse
import json
import re
from typing import Any

PROFILES = {"b0": "vibe-b0-research-only", "v0.2": "vibe-v0.2-research-only", "strong_pullback": "vibe-strong-pullback-research-only"}


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
    return {"schema_version": "stock-razor-vibe-research-request-v0.1", "status": "RESEARCH_ONLY", "profile": profile, "replay_engine": "src.services.strategy_lab.replay_baseline.replay", "rule_version": PROFILES[profile], "execution": "NOT_RUN", "oos": "NOT_VERIFIED", "radar_admission": "BLOCKED", "trade_execution": "NO", "prompt": prompt}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt")
    args = parser.parse_args()
    print(json.dumps(parse_request(args.prompt), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

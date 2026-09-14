#!/usr/bin/env python3
"""Validate the frozen research universe contract without network access."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.config.read_text(encoding="utf-8"))
    if payload.get("schema") != "radar-research-universe-v0.1":
        raise ValueError("unexpected universe schema")
    if payload.get("purpose") != "research_only" or payload.get("promotion_status") != "NOT_APPROVED":
        raise ValueError("universe must remain research-only and not approved")
    seen = set()
    count = 0
    for market, definition in payload.get("markets", {}).items():
        symbols = definition.get("symbols", [])
        if not definition.get("source_id") or not symbols:
            raise ValueError(f"invalid market definition: {market}")
        for symbol in symbols:
            if symbol in seen:
                raise ValueError(f"duplicate symbol: {symbol}")
            seen.add(symbol)
            count += 1
    if count == 0:
        raise ValueError("universe must not be empty")
    print(json.dumps({"status": "VALIDATED", "universe_id": payload["universe_id"], "symbol_count": count}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

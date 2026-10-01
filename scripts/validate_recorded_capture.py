#!/usr/bin/env python3
"""Validate a recorded EOD capture for Harness consumption."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the repository's src package importable when invoked from any cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.strategy_lab.market_data_capture import load_recorded_capture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--require-pit-approved", action="store_true")
    args = parser.parse_args()
    capture = load_recorded_capture(args.csv, args.manifest, require_pit_approved=args.require_pit_approved)
    capsule = capture.to_capsule(args.dataset_id, args.dataset_version)
    print(json.dumps({"status": "VALIDATED", "dataset_id": capsule.dataset_id,
                      "dataset_version": capsule.dataset_version,
                      "source_id": capsule.source_id, "event_count": len(capsule.events),
                      "fingerprint": capsule.fingerprint}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

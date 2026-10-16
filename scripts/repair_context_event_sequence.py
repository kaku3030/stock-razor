"""Explicit, hash-pinned metadata repair for the fixed AWS context store."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.services.context_manager import ContextManagerError, default_store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-events-sha256", required=True)
    args = parser.parse_args()
    store = default_store()
    root = Path("/var/lib/stock-razor/context-manager")
    if not args.execute or store.state_path != root / "current.json" or store.events_path != root / "events.jsonl":
        print("CONTEXT_EVENT_SEQUENCE_REPAIR=BLOCKED")
        return 2
    try:
        result = store.repair_version_sequence(expected_sha256=args.expected_events_sha256)
    except (ContextManagerError, OSError, ValueError, TypeError, KeyError):
        print("CONTEXT_EVENT_SEQUENCE_REPAIR=BLOCKED")
        return 2
    print("CONTEXT_EVENT_SEQUENCE_REPAIR=PASS")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

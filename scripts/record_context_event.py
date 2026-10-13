"""Append one sanitized Context Manager event without printing its payload."""

from __future__ import annotations

import argparse
import json

from src.services.context_manager import default_store


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-ref", default="")
    parser.add_argument("--payload-json", required=True)
    parser.add_argument("--ttl-seconds", type=int, default=86400)
    args = parser.parse_args()
    payload = json.loads(args.payload_json)
    result = default_store().record(
        event_id=args.event_id,
        event_type=args.event_type,
        source=args.source,
        source_ref=args.source_ref,
        payload=payload,
        ttl_seconds=args.ttl_seconds,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

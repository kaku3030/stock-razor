#!/usr/bin/env python3
"""Explicitly approve a recorded research capture for PIT validation.

This command is intentionally operator-driven; it never auto-approves data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--approver", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()

    payload = args.csv.read_bytes()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("status") != "CAPTURED_NOT_APPROVED":
        raise ValueError("only CAPTURED_NOT_APPROVED captures may be approved")
    digest = hashlib.sha256(payload).hexdigest()
    if manifest.get("raw_sha256") != digest:
        raise ValueError("capture manifest raw_sha256 mismatch")
    manifest.update({
        "status": "PIT_APPROVED",
        "pit_approved_at": datetime.now(timezone.utc).isoformat(),
        "pit_approved_by": args.approver,
        "pit_approval_reason": args.reason,
        "pit_approval_sha256": digest,
    })
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": manifest["status"],
        "approver": args.approver,
        "manifest": str(args.manifest),
        "sha256": digest,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

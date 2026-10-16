#!/usr/bin/env python3
"""Bounded read-only EC2 Feedback Hub storage audit.

A single successful read does NOT prove cross-run persistence, authenticated
producer delivery, automatic claim/writeback, or cloud autonomy admission.
Never prints database paths, source refs, identifiers, evidence, or secrets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

SCHEMA = "stock_razor_feedback_hub_ec2_readonly_v1"
MAX_DB_BYTES = 64 * 1024 * 1024
MAX_PATH_CHARS = 240
PATH_RE = re.compile(r"^/[A-Za-z0-9_./-]+$")
DISK_BACKING_CANDIDATES = frozenset({"ext4", "xfs", "btrfs", "zfs"})


def _path_allowed(raw: str) -> Path | None:
    if (not isinstance(raw, str) or len(raw) > MAX_PATH_CHARS
            or PATH_RE.fullmatch(raw) is None):
        return None
    path = Path(raw)
    if ".." in path.parts:
        return None
    try:
        # A symlink in any parent can silently redirect the requested
        # storage authority. Reject that alias before following the path.
        for component in (path, *path.parents):
            if component.is_symlink():
                return None
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or resolved.stat().st_size > MAX_DB_BYTES:
            return None
        # Never mistake a volatile runtime or scratch DB for durable storage.
        if any(resolved == Path(root) or Path(root) in resolved.parents
               for root in ("/run", "/tmp", "/dev/shm", "/proc", "/sys")):
            return None
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None


def _mount_class(path: Path, mountinfo: str) -> str:
    """Conservative backing classification; not a reboot persistence proof."""
    best = (-1, "UNKNOWN")
    for line in mountinfo.splitlines():
        before, sep, after = line.partition(" - ")
        if not sep:
            continue
        left = before.split()
        right = after.split()
        if len(left) < 5 or not right:
            continue
        mount = left[4].replace("\\040", " ")
        if not (str(path) == mount or str(path).startswith(mount.rstrip("/") + "/")):
            continue
        if len(mount) > best[0]:
            best = (len(mount), right[0].lower())
    if best[0] < 0 or best[1] not in DISK_BACKING_CANDIDATES:
        return "EPHEMERAL_OR_UNKNOWN"
    return "NON_VOLATILE_TYPE_OBSERVED_NOT_PROVEN"


def observe(db: str, *, mountinfo: str | None = None) -> dict:
    result = {
        "schema": SCHEMA, "status": "BLOCKED", "read_only": True,
        "existing_schema": "NOT_VERIFIED", "backing": "UNKNOWN",
        "audit_count": None, "open_p0": None, "open_p1": None,
        "audit_tail_digest": None,
        "cross_run_persistence": "NOT_VERIFIED",
        "producer_ingress": "NOT_VERIFIED",
        "claim_writeback": "NOT_VERIFIED",
        "trading_authority": False,
    }
    path = _path_allowed(db)
    if path is None:
        return result
    try:
        if mountinfo is None:
            mountinfo = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        result["backing"] = _mount_class(path, mountinfo)
        if result["backing"] != "NON_VOLATILE_TYPE_OBSERVED_NOT_PROVEN":
            return result
        uri = path.as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=3) as conn:
            conn.execute("PRAGMA query_only=ON")
            # Hold one consistent read snapshot for all count and digest
            # fields if other producers are concurrently appending events.
            conn.execute("BEGIN")
            version = conn.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone()
            if version != ("1",):
                return result
            for table in ("feedback", "audit"):
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if exists is None:
                    return result
            if conn.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                return result
            status_rows = conn.execute(
                "SELECT priority, COUNT(*) FROM feedback "
                "WHERE status IN ('NEW','CLAIMED','IN_PROGRESS') "
                "AND priority IN ('P0','P1') GROUP BY priority"
            ).fetchall()
            audit_count = conn.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
            tail = conn.execute(
                "SELECT sequence, event_id FROM audit "
                "ORDER BY sequence DESC LIMIT 16"
            ).fetchall()
        digest = hashlib.sha256(json.dumps(
            tail, separators=(",", ":"), ensure_ascii=True,
        ).encode("ascii")).hexdigest()[:16]
        counts = dict(status_rows)
        result.update(
            status="READBACK_ONLY",
            existing_schema="PASS",
            open_p0=int(counts.get("P0", 0)),
            open_p1=int(counts.get("P1", 0)),
            audit_count=int(audit_count),
            audit_tail_digest=digest,
        )
    except (OSError, UnicodeError, ValueError, TypeError, sqlite3.Error):
        # Never include exception messages: they may carry paths or SQL data.
        return result
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    print(json.dumps(observe(args.db), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()

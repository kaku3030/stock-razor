"""Bounded, redacted, persistent receipts for previously unknown engineering failures.

A receipt is diagnostic evidence, NOT a proved root cause or a trading signal.
No remote calls, model calls, provider access, or log/secret ingestion.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

SCHEMA = "stock-razor-unknown-incident-v1"
MAX_RECORDS = 128
MAX_BYTES = 100_000
SHA = re.compile(r"^[a-f0-9]{40}$")
QUEUE_SHA = re.compile(r"^[a-f0-9]{64}$")
SAFE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


class IncidentMemoryError(ValueError):
    pass


def _safe(value, field):
    if not isinstance(value, str) or not SAFE.fullmatch(value):
        raise IncidentMemoryError(field + "_INVALID")
    return value


def _read(path):
    if not path.exists():
        return {"schema": SCHEMA, "records": []}
    try:
        if path.stat().st_size > MAX_BYTES:
            raise IncidentMemoryError("INCIDENT_LEDGER_OVERSIZED")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, IncidentMemoryError):
            raise
        raise IncidentMemoryError("INCIDENT_LEDGER_UNREADABLE") from None
    if (not isinstance(value, dict) or set(value) != {"schema", "records"}
            or value["schema"] != SCHEMA or not isinstance(value["records"], list)
            or len(value["records"]) > MAX_RECORDS):
        raise IncidentMemoryError("INCIDENT_LEDGER_SCHEMA_INVALID")
    return value


def observe_failure(path, *, task_id, kind, exit_code, queue_sha,
                    source_sha="UNKNOWN", environment="UNKNOWN",
                    run_id="UNKNOWN", now=None):
    """One sanitized, atomic, idempotent receipt.

    This API deliberately accepts no error message, traceback or raw log text.
    Equal task/exit/queue across revisions has the same family fingerprint.
    Only equal fingerprint + source SHA + environment is a duplicate.
    """
    _safe(task_id, "TASK")
    _safe(kind, "KIND")
    _safe(environment, "ENVIRONMENT")
    _safe(run_id, "RUN_ID")
    if (not isinstance(exit_code, int) or isinstance(exit_code, bool)
            or not -255 <= exit_code <= 255):
        raise IncidentMemoryError("EXIT_CODE_INVALID")
    if not isinstance(queue_sha, str) or not QUEUE_SHA.fullmatch(queue_sha):
        raise IncidentMemoryError("QUEUE_SHA_INVALID")
    if source_sha != "UNKNOWN" and (not isinstance(source_sha, str) or not SHA.fullmatch(source_sha)):
        raise IncidentMemoryError("SOURCE_SHA_INVALID")
    stamp = (now or datetime.now(timezone.utc))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise IncidentMemoryError("INCIDENT_TIME_UNAWARE")
    timestamp = stamp.astimezone(timezone.utc).isoformat()
    key = json.dumps([task_id, kind, exit_code, queue_sha], separators=(",", ":"))
    fingerprint = hashlib.sha256(key.encode("ascii")).hexdigest()
    path = Path(path)
    ledger = _read(path)
    current = next((record for record in ledger["records"]
                    if record["fingerprint"] == fingerprint
                    and record["source_sha"] == source_sha
                    and record["environment"] == environment), None)
    if current:
        if not 1 <= current.get("observations", 0) <= 10**8:
            raise IncidentMemoryError("INCIDENT_COUNT_INVALID")
        current["observations"] += 1
        current["last_seen_utc"] = timestamp
        current["last_run_id"] = run_id
        action = "STOP_DUPLICATE"
    else:
        if len(ledger["records"]) >= MAX_RECORDS:
            raise IncidentMemoryError("INCIDENT_LEDGER_FULL")
        ledger["records"].append({
            "fingerprint": fingerprint,
            "task_id": task_id,
            "kind": kind,
            "exit_code": exit_code,
            "queue_sha": queue_sha,
            "source_sha": source_sha,
            "environment": environment,
            "first_seen_utc": timestamp,
            "last_seen_utc": timestamp,
            "first_run_id": run_id,
            "last_run_id": run_id,
            "observations": 1,
            "diagnosis": "UNKNOWN_PENDING_ROOT_CAUSE",
            "resolution": "UNVERIFIED",
        })
        action = "INVESTIGATE_ONCE"
    # One reviewed writer only. Don't claim cross-host transactions; GitHub
    # workflow artifacts retain this snapshot for readers in other windows.
    data = json.dumps(ledger, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise IncidentMemoryError("INCIDENT_LEDGER_OVERSIZED")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent,
                                         prefix="._incident_", delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        raise IncidentMemoryError("INCIDENT_LEDGER_WRITE_FAILED") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"schema": SCHEMA, "action": action, "fingerprint": fingerprint,
            "source_sha": source_sha, "diagnosis": "UNKNOWN_PENDING_ROOT_CAUSE",
            "evidence": "LOCAL_RECEIPT_ONLY_CLOUD_SYNC_NOT_VERIFIED"}


def summary(path):
    data = _read(Path(path))
    return {"schema": SCHEMA, "status": "OBSERVED", "count": len(data["records"]),
            "unresolved": sum(r["resolution"] != "VERIFIED" for r in data["records"]),
            "records": [{"fingerprint": r["fingerprint"][:12],
                         "task_id": r["task_id"], "source_sha": r["source_sha"],
                         "observations": r["observations"],
                         "diagnosis": r["diagnosis"]} for r in data["records"]]}

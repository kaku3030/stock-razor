"""Durable, fail-closed Feedback Hub for cloud autonomy runs.

The database is intentionally provider-neutral.  Cloud producers from either
market submit bounded, sanitized records; the mainline runner claims work in
an atomic transaction and writes an append-only audit trail.  The path must be
on persistent cloud storage for cross-run recovery; no Windows process is
required.
"""
from __future__ import annotations

import hashlib
import json
import re
from math import isfinite
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1
SOURCES = frozenset({"US_WINDOW", "CN_WINDOW", "US_RADAR", "CN_RADAR"})
PRIORITIES = frozenset({"P0", "P1"})
STATUSES = frozenset({"NEW", "CLAIMED", "IN_PROGRESS", "DONE", "BLOCKED", "FAILED"})
MAX_TEXT = 4000
MAX_EVIDENCE = 12000
MAX_ATTEMPTS = 3
DEFAULT_LEASE_SECONDS = 900
_ID_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,160}$")

# Explicit admission contract for producer-provided operational metadata.
# Keys outside this set require review before they can reach durable storage.
_EVIDENCE_KEYS = frozenset({
    "sha", "repo_sha", "runtime_sha", "run", "run_id", "ci", "status",
    "reason", "checks", "sequence", "frame_status", "bar_finality",
    "source_age_seconds", "latency_ms", "provider_requests",
    "observed_at_utc", "count", "attempt", "attempts", "evidence_id",
    "source", "error_code", "quality", "quality_flags", "source_status",
    "poll_status", "lease_state", "closed", "health", "symbol_count",
    "missing_bars", "timeframe",
})
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:authorization|bearer|api[_-]?key|password|passwd|"
    r"secret|credential|token|private[_-]?key|github_pat_|"
    r"gh[pousr]_|sk[-_]|AKIA[A-Z0-9]{10,}|ASIA[A-Z0-9]{10,}|"
    r"-----BEGIN|(?<![0-9])[0-9]{12}(?![0-9]))"
)
_SAFE_EVIDENCE_STRING = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/+\-]{0,255}$")
_MAX_EVIDENCE_DEPTH = 4
_MAX_EVIDENCE_ELEMENTS = 120
_EVIDENCE_ENUM_FIELDS = frozenset({
    "status", "reason", "source_status", "poll_status", "bar_finality",
    "quality", "health", "lease_state", "error_code",
})
_EVIDENCE_COUNT_FIELDS = frozenset({
    "run", "run_id", "sequence", "provider_requests", "count",
    "attempt", "attempts", "symbol_count", "missing_bars",
})
_EVIDENCE_DURATION_FIELDS = frozenset({"source_age_seconds", "latency_ms"})
_SAFE_STATUS = re.compile(r"^[A-Z][A-Z0-9_]{0,79}$")


class FeedbackHubError(ValueError):
    """Raised when the feedback contract is invalid or unavailable."""


@dataclass(frozen=True)
class FeedbackItem:
    id: str
    dedupe_key: str
    source: str
    priority: str
    title: str
    details: str
    evidence: dict[str, Any]
    owner: str | None
    status: str
    attempts: int
    max_attempts: int
    claimed_by: str | None
    lease_until: str | None
    source_ref: str
    created_at: str
    updated_at: str
    last_error: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    # Fixed precision makes new UTC stamps lexically sortable in SQLite.
    return value.astimezone(timezone.utc).isoformat(
        timespec="microseconds",
    ).replace("+00:00", "Z")


def _lease_deadline(value: object) -> datetime | None:
    """Read old second-only and new fractional UTC leases consistently."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _reject_sensitive_text(value: str) -> None:
    """Reject suspicious free text without logging the submitted value."""
    if _SENSITIVE_TEXT.search(value):
        raise FeedbackHubError("sensitive text is not allowed in feedback")


def _bounded_text(value: Any, field: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise FeedbackHubError(f"{field} must be a non-empty string of at most {limit} characters")
    _reject_sensitive_text(value)
    return value.strip()


def _safe_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only small, reviewed operational metadata; never raw payloads."""
    if not isinstance(value, Mapping):
        raise FeedbackHubError("evidence must be an object")
    visited = 0

    def check(item: Any, depth: int, field: str | None = None) -> None:
        nonlocal visited
        visited += 1
        if visited > _MAX_EVIDENCE_ELEMENTS or depth > _MAX_EVIDENCE_DEPTH:
            raise FeedbackHubError("evidence exceeds structural bounds")
        if field in _EVIDENCE_ENUM_FIELDS and (
            type(item) is not str or _SAFE_STATUS.fullmatch(item) is None
        ):
            raise FeedbackHubError("evidence enum is not allowlisted")
        if field in _EVIDENCE_COUNT_FIELDS and (
            type(item) is not int or item < 0
        ):
            raise FeedbackHubError("evidence count is not allowlisted")
        if field in _EVIDENCE_DURATION_FIELDS and (
            type(item) not in (int, float) or not isfinite(item) or item < 0
        ):
            raise FeedbackHubError("evidence duration is not allowlisted")
        if field == "closed" and type(item) is not bool:
            raise FeedbackHubError("evidence closure is not allowlisted")
        if isinstance(item, dict):
            if len(item) > 40:
                raise FeedbackHubError("evidence exceeds structural bounds")
            for key, nested in item.items():
                if not isinstance(key, str) or key not in _EVIDENCE_KEYS:
                    raise FeedbackHubError("evidence field is not allowlisted")
                check(nested, depth + 1, key)
        elif isinstance(item, list):
            if len(item) > 40:
                raise FeedbackHubError("evidence exceeds structural bounds")
            for nested in item:
                check(nested, depth + 1)
        elif isinstance(item, str):
            if not _SAFE_EVIDENCE_STRING.fullmatch(item):
                raise FeedbackHubError("evidence string is not allowlisted")
            _reject_sensitive_text(item)
        elif item is None or isinstance(item, bool) or type(item) is int:
            return
        elif type(item) is float and isfinite(item):
            return
        else:
            raise FeedbackHubError("evidence must be JSON-compatible")

    check(dict(value), 0)
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        )
        if len(encoded) > MAX_EVIDENCE:
            raise FeedbackHubError("evidence is too large")
        result = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FeedbackHubError("evidence must be JSON-compatible") from exc
    if not isinstance(result, dict):
        raise FeedbackHubError("evidence must be an object")
    return result


def make_dedupe_key(source: str, source_ref: str, title: str) -> str:
    canonical = "|".join((source, source_ref, title)).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class FeedbackHub:
    """SQLite-backed queue with atomic claims and auditable transitions."""

    def __init__(self, path: str | Path, *, require_existing: bool = False):
        self.path = Path(path)
        if require_existing and not self.path.is_file():
            raise FeedbackHubError("existing feedback hub is required")
        if not require_existing:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if require_existing:
                # Read-only SQLite URI rejects an absent database and never
                # initializes a phantom preflight store on a fresh CI runner.
                uri = self.path.resolve().as_uri() + "?mode=ro"
                self._connection = sqlite3.connect(
                    uri, uri=True, timeout=10, isolation_level=None,
                )
            else:
                self._connection = sqlite3.connect(
                    self.path, timeout=10, isolation_level=None,
                )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys=ON")
            if require_existing:
                self._verify_existing()
            else:
                self._connection.execute("PRAGMA journal_mode=WAL")
                self._initialize()
        except (sqlite3.Error, OSError) as exc:
            raise FeedbackHubError("feedback hub unavailable") from exc

    def _verify_existing(self) -> None:
        """Inspect an established Hub without creating or migrating tables."""
        row = self._connection.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()
        if row is None or row[0] != str(SCHEMA_VERSION):
            raise FeedbackHubError("existing feedback hub schema is invalid")
        for table in ("feedback", "audit"):
            found = self._connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if found is None:
                raise FeedbackHubError("existing feedback hub schema is invalid")

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                dedupe_key TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL,
                priority TEXT NOT NULL,
                title TEXT NOT NULL,
                details TEXT NOT NULL,
                evidence TEXT NOT NULL,
                owner TEXT,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL,
                claimed_by TEXT,
                lease_until TEXT,
                source_ref TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS audit (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                feedback_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                payload TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
            """
        )
        row = self._connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
        if row is None:
            self._connection.execute("INSERT INTO metadata(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
        elif row[0] != str(SCHEMA_VERSION):
            raise FeedbackHubError("unsupported feedback hub schema")

    def _audit(self, feedback_id: str, event_type: str, actor: str, payload: Mapping[str, Any]) -> None:
        self._connection.execute(
            "INSERT INTO audit(event_id, feedback_id, event_type, actor, payload, recorded_at) VALUES(?,?,?,?,?,?)",
            (uuid.uuid4().hex, feedback_id, event_type, actor, json.dumps(dict(payload), sort_keys=True), _timestamp(_now())),
        )

    @staticmethod
    def _item(row: sqlite3.Row) -> FeedbackItem:
        values = dict(row)
        values["evidence"] = json.loads(values["evidence"])
        return FeedbackItem(**values)

    def submit(
        self, *, source: str, priority: str, title: str, details: str,
        evidence: Mapping[str, Any], source_ref: str, owner: str | None = None,
        max_attempts: int = MAX_ATTEMPTS, dedupe_key: str | None = None,
    ) -> FeedbackItem:
        if source not in SOURCES or priority not in PRIORITIES:
            raise FeedbackHubError("source or priority is not allowlisted")
        source_ref = _bounded_text(source_ref, "source_ref")
        if not _ID_RE.fullmatch(source_ref):
            raise FeedbackHubError("source_ref has an invalid format")
        title, details = _bounded_text(title, "title"), _bounded_text(details, "details")
        if owner is not None:
            owner = _bounded_text(owner, "owner", 160)
        if type(max_attempts) is not int or not 1 <= max_attempts <= MAX_ATTEMPTS:
            raise FeedbackHubError("max_attempts is outside bounds")
        evidence = _safe_evidence(evidence)
        dedupe_key = dedupe_key or make_dedupe_key(source, source_ref, title)
        if not re.fullmatch(r"[0-9a-f]{64}", dedupe_key):
            raise FeedbackHubError("dedupe_key is invalid")
        now = _timestamp(_now())
        item_id = uuid.uuid4().hex
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute("SELECT * FROM feedback WHERE dedupe_key=?", (dedupe_key,)).fetchone()
            if existing is not None:
                self._connection.execute("COMMIT")
                return self._item(existing)
            self._connection.execute(
                "INSERT INTO feedback VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (item_id, dedupe_key, source, priority, title, details, json.dumps(evidence, sort_keys=True),
                 owner, "NEW", 0, max_attempts, None, None, source_ref, now, now, None),
            )
            self._audit(item_id, "SUBMITTED", owner or "producer", {"source": source, "priority": priority, "source_ref": source_ref})
            row = self._connection.execute("SELECT * FROM feedback WHERE id=?", (item_id,)).fetchone()
            self._connection.execute("COMMIT")
            return self._item(row)
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def preflight(self) -> dict[str, Any]:
        try:
            row = self._connection.execute(
                "SELECT COUNT(*) AS total FROM feedback WHERE status IN ('NEW','CLAIMED','IN_PROGRESS')"
            ).fetchone()
            priorities = self._connection.execute(
                "SELECT SUM(priority='P0') AS p0, SUM(priority='P1') AS p1 FROM feedback "
                "WHERE status IN ('NEW','CLAIMED','IN_PROGRESS')"
            ).fetchone()
            return {"status": "READY", "schema_version": SCHEMA_VERSION, "open": row["total"],
                    "open_p0": priorities["p0"] or 0, "open_p1": priorities["p1"] or 0}
        except sqlite3.Error as exc:
            raise FeedbackHubError("feedback hub preflight failed") from exc

    def claim(self, *, worker_id: str, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> FeedbackItem | None:
        worker_id = _bounded_text(worker_id, "worker_id", 160)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise FeedbackHubError("lease_seconds is outside bounds")
        now = _now()
        now_text = _timestamp(now)
        lease = _timestamp(now + timedelta(seconds=lease_seconds))
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                "SELECT * FROM feedback WHERE status IN ('NEW','CLAIMED','IN_PROGRESS') "
                "AND (lease_until IS NULL OR julianday(lease_until) <= julianday(?)) "
                "ORDER BY priority, created_at LIMIT 1", (now_text,)
            ).fetchone()
            if row is None:
                self._connection.execute("COMMIT")
                return None
            attempts = row["attempts"] + 1
            status = "CLAIMED" if attempts <= row["max_attempts"] else "BLOCKED"
            self._connection.execute(
                "UPDATE feedback SET status=?, attempts=?, claimed_by=?, lease_until=?, updated_at=? WHERE id=?",
                (status, attempts, worker_id, lease if status == "CLAIMED" else None, now_text, row["id"]),
            )
            self._audit(row["id"], "CLAIMED" if status == "CLAIMED" else "BLOCKED", worker_id, {"attempt": attempts})
            updated = self._connection.execute("SELECT * FROM feedback WHERE id=?", (row["id"],)).fetchone()
            self._connection.execute("COMMIT")
            return self._item(updated)
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def writeback(self, *, feedback_id: str, worker_id: str, status: str,
                  evidence: Mapping[str, Any], error: str | None = None) -> FeedbackItem:
        if status not in {"IN_PROGRESS", "DONE", "BLOCKED", "FAILED"}:
            raise FeedbackHubError("writeback status is not allowlisted")
        _bounded_text(worker_id, "worker_id", 160)
        evidence = _safe_evidence(evidence)
        if error is not None:
            error = _bounded_text(error, "error")
        now_dt = _now()
        now = _timestamp(now_dt)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone()
            if row is None or row["claimed_by"] != worker_id:
                raise FeedbackHubError("feedback claim is missing or owned by another worker")
            # Ownership alone is not write authority: DONE/BLOCKED/NEW are
            # terminal or unclaimed states, even if claimed_by was retained.
            if row["status"] not in {"CLAIMED", "IN_PROGRESS"}:
                raise FeedbackHubError("feedback claim is no longer active")
            # A worker with an expired lease must re-claim before writing,
            # even when another worker has not taken the item yet.
            lease_deadline = _lease_deadline(row["lease_until"])
            if lease_deadline is None or lease_deadline <= now_dt:
                raise FeedbackHubError("feedback claim lease expired")
            next_status = status
            if status == "FAILED":
                next_status = "NEW" if row["attempts"] < row["max_attempts"] else "BLOCKED"
            lease = None if next_status in {"DONE", "BLOCKED", "FAILED", "NEW"} else row["lease_until"]
            self._connection.execute("UPDATE feedback SET status=?, lease_until=?, updated_at=?, last_error=? WHERE id=?",
                                     (next_status, lease, now, error, feedback_id))
            self._audit(feedback_id, status, worker_id,
                        {"evidence": evidence, "error": error, "next_status": next_status})
            updated = self._connection.execute("SELECT * FROM feedback WHERE id=?", (feedback_id,)).fetchone()
            self._connection.execute("COMMIT")
            return self._item(updated)
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def audit(self, feedback_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute("SELECT * FROM audit WHERE feedback_id=? ORDER BY sequence", (feedback_id,)).fetchall()
        return [dict(row) for row in rows]


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    hub = FeedbackHub(args.db)
    try:
        print(json.dumps(hub.preflight(), sort_keys=True))
    finally:
        hub.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

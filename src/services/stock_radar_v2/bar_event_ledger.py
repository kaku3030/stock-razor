"""Durable, research-only inbox for already-qualified closed-bar candidates.

This is an isolated ledger seam, not a worker and not an admission switch. Callers
must run the canonical provider/session/freshness gate first. The ledger rechecks
closed-bar and finite OHLCV facts, persists before any downstream wake, and gives
consumers a stable idempotency key for their own deduplication.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from uuid import uuid4
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_SCHEMA_VERSION = "radar-closed-bar-event-v0.1"
_ALLOWED_TIMEFRAMES = frozenset({"1m", "5m", "15m", "1h", "1d"})
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_PAYLOAD_BYTES = 16_384
_MAX_KEY_PART = 96


class EventQueueFull(RuntimeError):
    """Raised before insert when the bounded pending/leased queue is full."""


@dataclass(frozen=True)
class ClosedBarEventCandidate:
    provider_id: str
    symbol: str
    timeframe: str
    bar_end: datetime
    observed_at: datetime
    exchange_timezone: str
    session_id: str
    session_status: str
    freshness_status: str
    quality_status: str
    quality_flags: tuple[str, ...]
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float
    source_revision: str
    source_runtime_id: str
    source_sequence: int
    rule_id: str
    rule_revision: str
    signal_kind: str
    evidence: Mapping[str, Any]
    is_closed: bool
    is_complete: bool
    _evidence_json: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in ("provider_id", "symbol", "session_id", "source_runtime_id",
                     "rule_id", "rule_revision", "signal_kind"):
            _required_token(name, getattr(self, name))
        if self.timeframe not in _ALLOWED_TIMEFRAMES:
            raise ValueError("unsupported candidate timeframe")
        if not _SHA_RE.fullmatch(self.source_revision):
            raise ValueError("source_revision must be a full lowercase git SHA")
        if isinstance(self.source_sequence, bool) or not isinstance(self.source_sequence, int) or self.source_sequence <= 0:
            raise ValueError("source_sequence must be a positive integer")
        if self.is_closed is not True or self.is_complete is not True:
            raise ValueError("only closed and complete bars can create candidates")
        if self.freshness_status != "FRESH":
            raise ValueError("candidate freshness must be FRESH")
        if self.quality_status != "PASS" or self.quality_flags:
            raise ValueError("candidate data quality must PASS without flags")
        if self.session_status != "CONFIRMED":
            raise ValueError("candidate session must be CONFIRMED")
        try:
            ZoneInfo(self.exchange_timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("exchange_timezone must be a known IANA timezone") from exc
        end = _aware_utc("bar_end", self.bar_end)
        observed = _aware_utc("observed_at", self.observed_at)
        if observed < end:
            raise ValueError("observed_at cannot precede the provider bar end")
        prices = {name: _finite_number(name, getattr(self, name)) for name in ("open", "high", "low", "close")}
        if any(value <= 0 for value in prices.values()):
            raise ValueError("OHLC values must be positive")
        if prices["low"] > min(prices["open"], prices["close"]) or prices["high"] < max(prices["open"], prices["close"]):
            raise ValueError("OHLC range does not contain open and close")
        if prices["low"] > prices["high"]:
            raise ValueError("low cannot exceed high")
        _finite_number("volume", self.volume, minimum=0)
        _finite_number("turnover", self.turnover, minimum=0)
        if not isinstance(self.evidence, Mapping):
            raise ValueError("candidate evidence must be an object")
        encoded = json.dumps(dict(self.evidence), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise ValueError("candidate evidence exceeds bounded payload size")
        snapshot = json.loads(encoded)
        _validate_evidence(snapshot)
        object.__setattr__(self, "_evidence_json", encoded)
        object.__setattr__(self, "evidence", snapshot)
        object.__setattr__(self, "quality_flags", tuple(self.quality_flags))

    @property
    def idempotency_key(self) -> str:
        end = _aware_utc("bar_end", self.bar_end).isoformat(timespec="microseconds").replace("+00:00", "Z")
        return "|".join((self.provider_id, self.symbol.strip().upper(), self.timeframe,
                         end, self.rule_id, self.rule_revision, self.signal_kind))

    @property
    def bar_id(self) -> str:
        identity = "|".join((self.provider_id, self.symbol.strip().upper(), self.timeframe,
                             _aware_utc("bar_end", self.bar_end).isoformat(timespec="microseconds").replace("+00:00", "Z")))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def immutable_payload(self) -> dict[str, Any]:
        # Receipt time, process identity and export sequence are first-observation
        # provenance. They may change on replay while the provider bar is identical.
        return {
            "schema_version": _SCHEMA_VERSION,
            "event_id": hashlib.sha256(self.idempotency_key.encode("utf-8")).hexdigest(),
            "idempotency_key": self.idempotency_key,
            "bar_id": self.bar_id,
            "provider_id": self.provider_id,
            "symbol": self.symbol.strip().upper(),
            "timeframe": self.timeframe,
            "bar_end_utc": _aware_utc("bar_end", self.bar_end).isoformat(),
            "exchange_timezone": self.exchange_timezone,
            "session_id": self.session_id,
            "session_status": self.session_status,
            "freshness_status": self.freshness_status,
            "quality_status": self.quality_status,
            "quality_flags": list(self.quality_flags),
            "is_closed": self.is_closed,
            "is_complete": self.is_complete,
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": float(self.volume),
            "turnover": float(self.turnover),
            "source_revision": self.source_revision,
            "rule_id": self.rule_id,
            "rule_revision": self.rule_revision,
            "signal_kind": self.signal_kind,
            "evidence": json.loads(self._evidence_json),
            "research_only": True,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }

    def first_observation_provenance(self) -> dict[str, Any]:
        return {
            "observed_at_utc": _aware_utc("observed_at", self.observed_at).isoformat(),
            "source_runtime_id": self.source_runtime_id,
            "source_sequence": self.source_sequence,
        }


@dataclass(frozen=True)
class RadarBarEvent:
    event_id: str
    idempotency_key: str
    payload: Mapping[str, Any]
    provenance: Mapping[str, Any]
    status: str
    attempts: int
    created_at: str
    wake_receipt_id: str | None = None


@dataclass(frozen=True)
class EventRecordResult:
    event: RadarBarEvent
    created: bool


@dataclass(frozen=True)
class WakeClaim:
    event: RadarBarEvent
    worker_id: str
    lease_token: str
    lease_expires_at: str
    attempt: int


class AIWakeBlocked(RuntimeError):
    """Bounded denial reason before any model invocation."""


@dataclass(frozen=True)
class AIWakeRecord:
    idempotency_key: str
    request_id: str
    status: str
    started_at: str
    deadline_at: str
    result: Mapping[str, Any] | None
    usage: Mapping[str, Any] | None
    reason: str | None


@dataclass(frozen=True)
class AIWakeReservation:
    record: AIWakeRecord
    created: bool
    invocation_token: str | None = field(default=None, repr=False)


class RadarBarEventLedger:
    """SQLite-backed bounded inbox/outbox for qualified research candidates."""

    def __init__(
        self,
        database: str | Path,
        *,
        max_pending: int = 1024,
        max_attempts: int = 5,
    ) -> None:
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("max_pending must be positive")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._database_path = None if str(database) == ":memory:" else Path(database).resolve()
        self._max_pending = int(max_pending)
        self._max_attempts = int(max_attempts)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(database), timeout=5.0, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA synchronous = FULL")
        if str(database) != ":memory:":
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS stock_radar_bar_event_ledger (
                idempotency_key TEXT PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('PENDING','CLAIMED','ACKNOWLEDGED','DEAD_LETTER')),
                attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
                created_at TEXT NOT NULL,
                lease_owner TEXT,
                lease_expires_at TEXT,
                wake_receipt_id TEXT
            );
            CREATE TABLE IF NOT EXISTS stock_radar_ai_wake (
                idempotency_key TEXT PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL CHECK(status IN ('STARTED','SUCCEEDED','UNKNOWN')),
                invocation_token TEXT NOT NULL,
                started_at TEXT NOT NULL,
                deadline_at TEXT NOT NULL,
                result_json TEXT,
                usage_json TEXT,
                reason TEXT,
                FOREIGN KEY(idempotency_key) REFERENCES stock_radar_bar_event_ledger(idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS ix_stock_radar_bar_event_queue
                ON stock_radar_bar_event_ledger(status, created_at, event_id);
            """
        )

    def __enter__(self) -> "RadarBarEventLedger":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def record(
        self, candidate: ClosedBarEventCandidate, *, recorded_at: datetime | None = None
    ) -> EventRecordResult:
        if not isinstance(candidate, ClosedBarEventCandidate):
            raise TypeError("candidate must be ClosedBarEventCandidate")
        created = _aware_utc("recorded_at", recorded_at or datetime.now(timezone.utc)).isoformat()
        payload = candidate.immutable_payload()
        payload_json = _canonical_json(payload)
        provenance_json = _canonical_json(candidate.first_observation_provenance())
        if len(payload_json.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
            raise ValueError("candidate payload exceeds bounded size")
        with self._lock:
            connection = self._connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT * FROM stock_radar_bar_event_ledger WHERE idempotency_key = ?",
                    (candidate.idempotency_key,),
                ).fetchone()
                if existing is not None:
                    if str(existing["payload_json"]) != payload_json:
                        raise ValueError("conflicting duplicate for existing event idempotency key")
                    connection.commit()
                    return EventRecordResult(event=self._event(existing), created=False)
                outstanding = connection.execute(
                    "SELECT COUNT(*) AS count FROM stock_radar_bar_event_ledger WHERE status IN ('PENDING','CLAIMED')"
                ).fetchone()
                if int(outstanding["count"]) >= self._max_pending:
                    raise EventQueueFull("radar event queue capacity reached; candidate was not persisted")
                connection.execute(
                    """
                    INSERT INTO stock_radar_bar_event_ledger
                        (idempotency_key,event_id,payload_json,provenance_json,status,attempts,created_at)
                    VALUES (?,?,?,?,'PENDING',0,?)
                    """,
                    (candidate.idempotency_key, payload["event_id"], payload_json, provenance_json, created),
                )
                row = connection.execute(
                    "SELECT * FROM stock_radar_bar_event_ledger WHERE idempotency_key = ?",
                    (candidate.idempotency_key,),
                ).fetchone()
                connection.commit()
                return EventRecordResult(event=self._event(row), created=True)
            except Exception:
                connection.rollback()
                raise

    def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime | None = None,
        lease_seconds: int = 30,
    ) -> WakeClaim | None:
        _required_token("worker_id", worker_id)
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        timestamp = _aware_utc("now", now or datetime.now(timezone.utc))
        now_text = timestamp.isoformat()
        expires_text = (timestamp + timedelta(seconds=lease_seconds)).isoformat()
        with self._lock:
            connection = self._connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    UPDATE stock_radar_bar_event_ledger
                    SET status='DEAD_LETTER', lease_owner=NULL, lease_expires_at=NULL
                    WHERE status='CLAIMED' AND lease_expires_at <= ? AND attempts >= ?
                    """,
                    (now_text, self._max_attempts),
                )
                row = connection.execute(
                    """
                    SELECT * FROM stock_radar_bar_event_ledger
                    WHERE status='PENDING' OR (status='CLAIMED' AND lease_expires_at <= ?)
                    ORDER BY created_at, event_id LIMIT 1
                    """,
                    (now_text,),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                attempt = int(row["attempts"]) + 1
                connection.execute(
                    """
                    UPDATE stock_radar_bar_event_ledger
                    SET status='CLAIMED', attempts=?, lease_owner=?, lease_expires_at=?
                    WHERE idempotency_key=?
                    """,
                    (attempt, uuid4().hex, expires_text, str(row["idempotency_key"])),
                )
                updated = connection.execute(
                    "SELECT * FROM stock_radar_bar_event_ledger WHERE idempotency_key = ?",
                    (str(row["idempotency_key"]),),
                ).fetchone()
                connection.commit()
                event = self._event(updated)
                return WakeClaim(
                    event=event,
                    worker_id=worker_id,
                    lease_token=str(updated["lease_owner"]),
                    lease_expires_at=expires_text,
                    attempt=attempt,
                )
            except Exception:
                connection.rollback()
                raise

    def acknowledge(
        self,
        idempotency_key: str,
        *,
        lease_token: str,
        receipt_id: str,
        now: datetime | None = None,
    ) -> RadarBarEvent:
        _required_token("lease_token", lease_token)
        _required_token("receipt_id", receipt_id)
        timestamp = _aware_utc("now", now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            connection = self._connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM stock_radar_bar_event_ledger WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row is None:
                    raise KeyError(idempotency_key)
                if row["status"] == "ACKNOWLEDGED":
                    if row["wake_receipt_id"] != receipt_id:
                        raise ValueError("acknowledged wake receipt conflicts")
                    connection.commit()
                    return self._event(row)
                if (
                    row["status"] != "CLAIMED"
                    or row["lease_owner"] != lease_token
                    or not row["lease_expires_at"]
                    or str(row["lease_expires_at"]) <= timestamp
                ):
                    raise PermissionError("current unexpired event lease is required")
                connection.execute(
                    """
                    UPDATE stock_radar_bar_event_ledger
                    SET status='ACKNOWLEDGED', lease_owner=NULL, lease_expires_at=NULL, wake_receipt_id=?
                    WHERE idempotency_key=?
                    """,
                    (receipt_id, idempotency_key),
                )
                updated = connection.execute(
                    "SELECT * FROM stock_radar_bar_event_ledger WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                connection.commit()
                return self._event(updated)
            except Exception:
                connection.rollback()
                raise

    def release_for_retry(
        self,
        idempotency_key: str,
        *,
        lease_token: str,
        now: datetime | None = None,
    ) -> RadarBarEvent:
        _required_token("lease_token", lease_token)
        timestamp = _aware_utc("now", now or datetime.now(timezone.utc)).isoformat()
        with self._lock:
            connection = self._connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM stock_radar_bar_event_ledger WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row is None:
                    raise KeyError(idempotency_key)
                if (
                    row["status"] != "CLAIMED"
                    or row["lease_owner"] != lease_token
                    or not row["lease_expires_at"]
                    or str(row["lease_expires_at"]) <= timestamp
                ):
                    raise PermissionError("current unexpired event lease is required")
                status = "PENDING" if int(row["attempts"]) < self._max_attempts else "DEAD_LETTER"
                connection.execute(
                    """
                    UPDATE stock_radar_bar_event_ledger
                    SET status=?, lease_owner=NULL, lease_expires_at=NULL
                    WHERE idempotency_key=?
                    """,
                    (status, idempotency_key),
                )
                updated = connection.execute(
                    "SELECT * FROM stock_radar_bar_event_ledger WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                connection.commit()
                return self._event(updated)
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _ai_wake(row: sqlite3.Row) -> AIWakeRecord:
        return AIWakeRecord(
            idempotency_key=str(row["idempotency_key"]), request_id=str(row["request_id"]),
            status=str(row["status"]), started_at=str(row["started_at"]),
            deadline_at=str(row["deadline_at"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            usage=json.loads(row["usage_json"]) if row["usage_json"] else None,
            reason=str(row["reason"]) if row["reason"] else None,
        )

    def get_ai_wake(self, idempotency_key: str, *, now: datetime | None = None) -> AIWakeRecord:
        timestamp = _aware_utc("now", now or datetime.now(timezone.utc)).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE stock_radar_ai_wake SET status='UNKNOWN', reason='AI_DEADLINE_EXPIRED' "
                "WHERE idempotency_key=? AND status='STARTED' AND deadline_at<=?",
                (idempotency_key, timestamp),
            )
            row = self._connection.execute(
                "SELECT * FROM stock_radar_ai_wake WHERE idempotency_key=?", (idempotency_key,),
            ).fetchone()
        if row is None:
            raise KeyError(idempotency_key)
        return self._ai_wake(row)

    def begin_ai_wake(
        self, claim: WakeClaim, *, now: datetime, timeout_seconds: int, max_calls: int,
    ) -> AIWakeReservation:
        """Commit one invocation intent under the current event lease and DB budget.

        STARTED is never retried automatically: a lost process/response cannot
        prove that the external provider did not execute or charge the request.
        """
        if not isinstance(claim, WakeClaim):
            raise TypeError("claim must be WakeClaim")
        for name, value, bound in (("timeout_seconds", timeout_seconds, 60), ("max_calls", max_calls, 100)):
            if type(value) is not int or not 1 <= value <= bound:
                raise ValueError(f"{name} outside bounds")
        observed = _aware_utc("now", now)
        timestamp = observed.isoformat()
        key = claim.event.idempotency_key
        with self._lock:
            db = self._connection
            db.execute("BEGIN IMMEDIATE")
            try:
                event = db.execute(
                    "SELECT * FROM stock_radar_bar_event_ledger WHERE idempotency_key=?", (key,),
                ).fetchone()
                if (event is None or event["status"] != "CLAIMED"
                        or event["lease_owner"] != claim.lease_token or event["lease_expires_at"] <= timestamp):
                    raise PermissionError("current unexpired event lease is required")
                db.execute(
                    "UPDATE stock_radar_ai_wake SET status='UNKNOWN', reason='AI_DEADLINE_EXPIRED' "
                    "WHERE status='STARTED' AND deadline_at<=?", (timestamp,),
                )
                existing = db.execute("SELECT * FROM stock_radar_ai_wake WHERE idempotency_key=?", (key,)).fetchone()
                if existing is not None:
                    db.commit()
                    return AIWakeReservation(self._ai_wake(existing), False)
                unresolved = db.execute("SELECT 1 FROM stock_radar_ai_wake WHERE status IN ('STARTED','UNKNOWN') LIMIT 1").fetchone()
                if unresolved:
                    # Keep expiry -> UNKNOWN evidence even when new dispatch is denied.
                    db.commit()
                    raise AIWakeBlocked("AI_UNRESOLVED_INVOCATION")
                count = db.execute("SELECT COUNT(*) FROM stock_radar_ai_wake").fetchone()[0]
                if count >= max_calls:
                    raise AIWakeBlocked("AI_CALL_BUDGET_EXHAUSTED")
                request_id = hashlib.sha256(("research-ai-v1|" + key).encode("utf-8")).hexdigest()
                invocation_token = uuid4().hex
                db.execute(
                    "INSERT INTO stock_radar_ai_wake "
                    "(idempotency_key,request_id,status,invocation_token,started_at,deadline_at) "
                    "VALUES (?,?,'STARTED',?,?,?)",
                    (key, request_id, invocation_token, timestamp,
                     (observed + timedelta(seconds=timeout_seconds)).isoformat()),
                )
                row = db.execute("SELECT * FROM stock_radar_ai_wake WHERE idempotency_key=?", (key,)).fetchone()
                db.commit()
                return AIWakeReservation(self._ai_wake(row), True, invocation_token)
            except Exception:
                db.rollback()
                raise

    def complete_ai_wake(
        self, idempotency_key: str, *, invocation_token: str,
        result: Mapping[str, Any], usage: Mapping[str, Any], now: datetime,
    ) -> AIWakeRecord:
        _required_token("invocation_token", invocation_token)
        if (not isinstance(result, Mapping) or set(result) != {"event_id", "assessment", "evidence_fields"}
                or not isinstance(result["assessment"], str)
                or result["assessment"] not in {"WATCH", "NO_SIGNAL"}
                or not isinstance(result["evidence_fields"], list)
                or not result["evidence_fields"] or len(result["evidence_fields"]) > 7
                or any(not isinstance(field, str) or field not in {"open", "high", "low", "close", "volume", "turnover", "bar_end_utc"}
                       for field in result["evidence_fields"])):
            raise ValueError("invalid research observation result")
        if (not isinstance(usage, Mapping) or set(usage) != {"prompt_tokens", "completion_tokens", "total_tokens"}
                or any(type(value) is not int or not 0 <= value <= 2_000_000_000 for value in usage.values())
                or usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]
                or usage["total_tokens"] == 0):
            raise ValueError("invalid provider token usage")
        result_json, usage_json = _canonical_json(dict(result)), _canonical_json(dict(usage))
        timestamp = _aware_utc("now", now).isoformat()
        with self._lock:
            db = self._connection
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute("SELECT * FROM stock_radar_ai_wake WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if row is None or row["invocation_token"] != invocation_token:
                    raise PermissionError("invocation ownership is required")
                event = db.execute("SELECT event_id FROM stock_radar_bar_event_ledger WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if result["event_id"] != event["event_id"]:
                    raise ValueError("AI result event identity mismatch")
                if row["status"] == "SUCCEEDED":
                    if row["result_json"] != result_json or row["usage_json"] != usage_json:
                        raise ValueError("conflicting AI result")
                elif row["status"] == "STARTED":
                    if timestamp < row["started_at"] or row["deadline_at"] <= timestamp:
                        db.execute("UPDATE stock_radar_ai_wake SET status='UNKNOWN', reason='AI_DEADLINE_EXPIRED' WHERE idempotency_key=?", (idempotency_key,))
                    else:
                        db.execute("UPDATE stock_radar_ai_wake SET status='SUCCEEDED',result_json=?,usage_json=? WHERE idempotency_key=?", (result_json, usage_json, idempotency_key))
                updated = db.execute("SELECT * FROM stock_radar_ai_wake WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                db.commit()
                return self._ai_wake(updated)
            except Exception:
                db.rollback()
                raise

    def mark_ai_wake_unknown(self, idempotency_key: str, *, invocation_token: str) -> AIWakeRecord:
        _required_token("invocation_token", invocation_token)
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE stock_radar_ai_wake SET status='UNKNOWN', reason='AI_RESULT_NOT_VERIFIED' "
                "WHERE idempotency_key=? AND invocation_token=? AND status='STARTED'",
                (idempotency_key, invocation_token),
            )
            row = self._connection.execute("SELECT * FROM stock_radar_ai_wake WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if row is None or row["invocation_token"] != invocation_token:
                raise PermissionError("invocation ownership is required")
        return self._ai_wake(row)

    def get(self, idempotency_key: str) -> RadarBarEvent:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM stock_radar_bar_event_ledger WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row is None:
            raise KeyError(idempotency_key)
        return self._event(row)

    @property
    def database_path(self) -> Path | None:
        return self._database_path

    def runtime_summary(self, *, now: datetime | None = None) -> dict[str, Any]:
        """One read-only snapshot; no payloads, lease/intent changes or provider I/O."""
        stamp = _aware_utc("now", now or datetime.now(timezone.utc)).isoformat()
        event_states = {"event_pending": "PENDING", "event_claimed": "CLAIMED",
                        "event_acknowledged": "ACKNOWLEDGED", "event_dead_letter": "DEAD_LETTER"}
        ai_states = {"ai_started": "STARTED", "ai_succeeded": "SUCCEEDED", "ai_unknown": "UNKNOWN"}
        columns = [f"(SELECT COUNT(*) FROM stock_radar_bar_event_ledger WHERE status='{state}') AS {name}"
                   for name, state in event_states.items()]
        columns += [f"(SELECT COUNT(*) FROM stock_radar_ai_wake WHERE status='{state}') AS {name}"
                    for name, state in ai_states.items()]
        columns += ["(SELECT COUNT(*) FROM stock_radar_ai_wake WHERE status='STARTED' AND deadline_at<=?) AS ai_expired",
                    "(SELECT MIN(created_at) FROM stock_radar_bar_event_ledger WHERE status IN ('PENDING','CLAIMED')) AS oldest_pending_at"]
        with self._lock:
            return dict(self._connection.execute("SELECT " + ",".join(columns), (stamp,)).fetchone())

    def pending_count(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM stock_radar_bar_event_ledger WHERE status IN ('PENDING','CLAIMED')"
            ).fetchone()
        return int(row["count"])

    def dead_letter_count(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM stock_radar_bar_event_ledger WHERE status='DEAD_LETTER'"
            ).fetchone()
        return int(row["count"])

    @staticmethod
    def _event(row: sqlite3.Row) -> RadarBarEvent:
        payload = json.loads(str(row["payload_json"]))
        return RadarBarEvent(
            event_id=str(row["event_id"]),
            idempotency_key=str(row["idempotency_key"]),
            payload=payload,
            provenance=json.loads(str(row["provenance_json"])),
            status=str(row["status"]),
            attempts=int(row["attempts"]),
            created_at=str(row["created_at"]),
            wake_receipt_id=str(row["wake_receipt_id"]) if row["wake_receipt_id"] else None,
        )


def _required_token(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} is required and must be a trimmed string")
    if len(value.encode("utf-8")) > _MAX_KEY_PART or "|" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{name} contains invalid characters or exceeds its limit")


def _aware_utc(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _finite_number(name: str, value: Any, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    normalized = float(value)
    if minimum is not None and normalized < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return normalized


def _validate_evidence(value: Any, *, depth: int = 0) -> None:
    if depth > 4:
        raise ValueError("candidate evidence nesting exceeds its limit")
    if isinstance(value, Mapping):
        if len(value) > 128:
            raise ValueError("candidate evidence object exceeds its field limit")
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or not key
                or len(key.encode("utf-8")) > 64
                or re.search(r"(?i)(secret|password|token|api[_-]?key|authorization|cookie|credential|webhook|account[_-]?id)", key)
            ):
                raise ValueError("candidate evidence contains a sensitive or invalid field name")
            _validate_evidence(item, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > 128:
            raise ValueError("candidate evidence list exceeds its item limit")
        for item in value:
            _validate_evidence(item, depth=depth + 1)
        return
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if (
            len(value.encode("utf-8")) > 512
            or "\n" in value
            or "\r" in value
            or re.search(r"(?i)(https?://|bearer\s|(?:sk|ghp|gho|github_pat|xoxb)[_-][a-z0-9_-]{10,})", value)
        ):
            raise ValueError("candidate evidence contains unsafe text")
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise ValueError("candidate evidence values must be bounded JSON scalars or containers")


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

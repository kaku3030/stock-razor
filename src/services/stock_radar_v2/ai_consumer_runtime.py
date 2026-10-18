"""Bounded research consumer loop and independent, fail-closed status assessment.

No backend discovery, currency-budget attestation, service installation or I/O to
models/notifications is performed here. An admitted caller must inject a backend.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
from uuid import uuid4

from engineering_autonomy.loop import stop_requested
from src.services.stock_radar_v2.ai_event_consumer import AIConsumerLimits, RadarAIEventConsumer
from src.services.stock_radar_v2.bar_event_ledger import RadarBarEventLedger

_SCHEMA = "radar-ai-runtime-v1"
_COUNTS = {"event_pending", "event_claimed", "event_acknowledged", "event_dead_letter",
           "ai_started", "ai_succeeded", "ai_unknown", "ai_expired"}
_PHASES = {"POLLING", "WAITING", "STOPPED", "HALTED", "DISABLED", "FAILED", "LIMIT_REACHED"}


def open_worker_event_ledger(*, enabled: bool = False, state_directory=None, reserved_paths=()):
    """Use systemd-owned persistent storage; disabled workers open no database."""
    if type(enabled) is not bool:
        raise ValueError("event ledger enablement must be boolean")
    if not enabled:
        return None
    root = Path(state_directory or "")
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("existing absolute persistent StateDirectory is required")
    database = root / "closed-bar-events.sqlite"
    _check_paths(database.resolve(), reserved_paths)
    return RadarBarEventLedger(database)


def _check_paths(database, paths):
    if database is not None:
        protected = {database, Path(str(database) + "-wal"), Path(str(database) + "-shm")}
        if any(Path(path).resolve() in protected for path in paths):
            raise ValueError("runtime artifacts must not replace ledger files")


def _time(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware UTC time required")
    return value.astimezone(timezone.utc)


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("exact lowercase SHA required")
    return value


def _publish(path, payload):
    """Publish private categorical telemetry before permitting consumer progress."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, allow_nan=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        raise RuntimeError("AI_RUNTIME_STATUS_WRITE_FAILED") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                raise RuntimeError("AI_RUNTIME_STATUS_WRITE_FAILED") from None


def run_ai_consumer(ledger, *, expected_source_sha, worker_sha, status_path, stop_file,
                    backend=None, enabled=False, limits=None, max_cycles=1,
                    max_runtime_seconds=120, poll_seconds=1,
                    now=lambda: datetime.now(timezone.utc), clock=time.monotonic, wait=time.sleep):
    """Run finite admitted polls; no automatic restart or retry of unknown requests.

    Caller owns the ledger, one status-file writer and independent supervision.
    Stop is cooperative between polls; a sent remote request cannot be recalled.
    """
    _sha(expected_source_sha)
    _sha(worker_sha)
    for value, maximum in ((max_cycles, 10000), (max_runtime_seconds, 7200), (poll_seconds, 30)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError("runtime limit outside bounds")
    limits = limits or AIConsumerLimits()
    runtime_id, sequence, started = uuid4().hex, 0, clock()
    consumer = RadarAIEventConsumer(ledger, expected_source_sha=expected_source_sha,
        worker_id=runtime_id, backend=backend, enabled=enabled, limits=limits, now=now)
    status_path, stop_file = Path(status_path), Path(stop_file)
    if enabled and backend is not None and ledger.database_path is None:
        raise ValueError("persistent ledger required for enabled runtime")
    _check_paths(ledger.database_path, (status_path, stop_file))
    if status_path.resolve() == stop_file.resolve():
        raise ValueError("status and stop paths must differ")
    consumer_status = "DISABLED"

    def publish(phase, *, polling=False):
        nonlocal sequence
        stamp = _time(now())
        sequence += 1
        queue = ledger.runtime_summary(now=stamp)
        calls = queue["ai_started"] + queue["ai_succeeded"] + queue["ai_unknown"]
        payload = {"schema": _SCHEMA, "runtime_id": runtime_id, "sequence": sequence,
            "worker_sha": worker_sha, "expected_source_sha": expected_source_sha,
            "emitted_at": stamp.isoformat(), "phase": phase, "consumer_status": consumer_status,
            "poll_deadline": (stamp + timedelta(seconds=limits.timeout_seconds + 30)).isoformat() if polling else None,
            "queue": queue, "remaining_calls": max(0, limits.max_calls - calls),
            "research_only": True, "radar_admission": "BLOCKED", "live_trade": False,
            "cost_status": "UNKNOWN", "cloud_acceptance": "NOT_VERIFIED"}
        _publish(status_path, payload)
        return payload

    for _ in range(max_cycles):
        if stop_requested(stop_file):
            return publish("STOPPED")
        if not enabled or backend is None:
            return publish("DISABLED")
        if max_runtime_seconds - (clock() - started) < limits.timeout_seconds + 30:
            return publish("LIMIT_REACHED")
        publish("POLLING", polling=True)
        try:
            consumer_status = consumer.poll_once().status
        except Exception:
            consumer_status = "UNKNOWN"
            return publish("FAILED")
        if stop_requested(stop_file):
            return publish("STOPPED")
        if consumer_status in {"UNKNOWN", "BLOCKED", "IN_PROGRESS"}:
            return publish("HALTED")
        publish("WAITING")
        remaining = max_runtime_seconds - (clock() - started)
        if remaining <= 0:
            break
        if _ + 1 < max_cycles:
            wait(min(poll_seconds, remaining))
    return publish("LIMIT_REACHED")


def assess_runtime(payload, *, expected_worker_sha, expected_source_sha, now=None, max_age_seconds=60):
    """Assess observed progress evidence; never promote it to deployment/market PASS."""
    _sha(expected_worker_sha)
    _sha(expected_source_sha)
    stamp = _time(now or datetime.now(timezone.utc))
    if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 120:
        raise ValueError("monitor age outside bounds")
    verdict = {"status": "UNKNOWN", "research_only": True, "radar_admission": "BLOCKED",
               "live_trade": False, "cost_status": "UNKNOWN", "cloud_acceptance": "NOT_VERIFIED"}
    try:
        if (not isinstance(payload, dict) or payload["schema"] != _SCHEMA
                or payload["worker_sha"] != expected_worker_sha or payload["expected_source_sha"] != expected_source_sha
                or payload["research_only"] is not True or payload["radar_admission"] != "BLOCKED"
                or payload["live_trade"] is not False or payload["cost_status"] != "UNKNOWN"
                or payload["cloud_acceptance"] != "NOT_VERIFIED"
                or not re.fullmatch(r"[0-9a-f]{32}", payload["runtime_id"])
                or type(payload["sequence"]) is not int or payload["sequence"] < 1
                or payload["phase"] not in _PHASES):
            return verdict
        emitted = _time(datetime.fromisoformat(payload["emitted_at"]))
        age = (stamp - emitted).total_seconds()
        queue = payload["queue"]
        if (not isinstance(queue, dict) or set(queue) != _COUNTS | {"oldest_pending_at"}
                or any(type(queue[name]) is not int or not 0 <= queue[name] <= 10**9 for name in _COUNTS)
                or queue["ai_expired"] > queue["ai_started"] or age < 0):
            return verdict
        oldest = queue["oldest_pending_at"]
        backlog_age = None if oldest is None else (stamp - _time(datetime.fromisoformat(oldest))).total_seconds()
        if (oldest is None) != (queue["event_pending"] + queue["event_claimed"] == 0) or (backlog_age is not None and backlog_age < 0):
            return verdict
        phase = payload["phase"]
        if phase == "POLLING":
            deadline = _time(datetime.fromisoformat(payload["poll_deadline"]))
            if not 0 < (deadline - emitted).total_seconds() <= 90:
                return verdict
            status = ("STALLED" if stamp > deadline else
                      "BLOCKED" if queue["ai_unknown"] or queue["ai_expired"] else "BUSY")
        elif payload["poll_deadline"] is not None:
            return verdict
        elif age > max_age_seconds:
            status = "STALE"
        elif queue["ai_unknown"] or queue["ai_expired"] or phase in {"HALTED", "FAILED"}:
            status = "BLOCKED"
        elif phase in {"STOPPED", "DISABLED", "LIMIT_REACHED"}:
            status = phase
        elif queue["event_dead_letter"] or (backlog_age is not None and backlog_age > 120):
            status = "DEGRADED"
        else:
            status = "OBSERVED"
        return {**verdict, "status": status, "heartbeat_age_seconds": age, "queue": dict(queue)}
    except (ValueError, TypeError, KeyError, OverflowError):
        return verdict

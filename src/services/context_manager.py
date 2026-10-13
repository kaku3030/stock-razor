"""Small, fail-closed context state store for cross-chat recovery.

The store is deliberately independent from conversation history. Producers
append bounded engineering events; readers consume one compact current state.
It never stores credentials and never grants market, paper, or trading access.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA_VERSION = "stock-razor-context-manager-v1"
STATE_PATH_ENV = "STOCK_RAZOR_CONTEXT_STATE_PATH"
EVENTS_PATH_ENV = "STOCK_RAZOR_CONTEXT_EVENTS_PATH"
KNOWN_SOURCES = frozenset({"engineering", "deployment", "ci", "radar", "mcp", "system"})
RECOVERY_DOMAINS = ("ci", "pr", "deploy", "radar", "blockers", "priorities")
_SENSITIVE_KEY = re.compile(r"(?:secret|token|password|api[_-]?key|authorization|cookie|private[_-]?key|access[_-]?key|refresh)", re.I)
_SENSITIVE_VALUE = re.compile(r"(?:bearer\s+|-----BEGIN|(?:sk|ghp|github_pat|AKIA)[A-Za-z0-9_\-]{8,})", re.I)


class ContextManagerError(ValueError):
    """Raised when an event cannot be safely persisted or verified."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContextManagerError("timestamp must include timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ContextManagerError("invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContextManagerError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _sanitize(value: Any, *, key: str = "") -> Any:
    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): _sanitize(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        if _SENSITIVE_VALUE.search(value):
            return "[REDACTED]"
        return value[:4096]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ContextManagerError("payload must contain JSON-compatible values")


def _gates() -> dict[str, Any]:
    return {
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "paper_auto_ready": False,
        "live_trade": False,
    }


class ContextManagerStore:
    """Atomic current-state plus append-only event log."""

    def __init__(
        self,
        state_path: str | Path,
        events_path: str | Path | None = None,
        *,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.state_path = Path(state_path)
        self.events_path = Path(events_path or self.state_path.with_name("events.jsonl"))
        self.clock = clock

    def record(
        self,
        *,
        event_id: str,
        event_type: str,
        source: str,
        payload: Mapping[str, Any],
        source_ref: str = "",
        occurred_at: datetime | None = None,
        ttl_seconds: int = 86400,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", event_id):
            raise ContextManagerError("event_id is invalid")
        if not event_type or len(event_type) > 80 or source not in KNOWN_SOURCES:
            raise ContextManagerError("event_type or source is invalid")
        if not isinstance(payload, Mapping):
            raise ContextManagerError("payload must be an object")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 30 * 86400:
            raise ContextManagerError("ttl_seconds must be between 1 and 2592000")
        now = self.clock()
        occurred = occurred_at or now
        expires = now + timedelta(seconds=ttl_seconds)
        safe_payload = _sanitize(payload)
        fingerprint = _fingerprint(safe_payload)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        events = self._read_events()
        existing = next((item for item in events if item.get("event_id") == event_id), None)
        if existing is not None:
            if existing.get("fingerprint") != fingerprint:
                raise ContextManagerError("event_id already exists with different payload")
            self._atomic_write(self._current_from_events(events, now=now))
            return {"status": "DUPLICATE", "event_id": event_id, "version": existing.get("version")}
        version = (events[-1].get("version", 0) if events else 0) + 1
        event = {
            "schema_version": SCHEMA_VERSION,
            "version": version,
            "event_id": event_id,
            "event_type": event_type,
            "source": source,
            "source_ref": str(source_ref)[:512],
            "occurred_at": _timestamp(occurred),
            "recorded_at": _timestamp(now),
            "expires_at": _timestamp(expires),
            "fingerprint": fingerprint,
            "payload": safe_payload,
        }
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        current = self._current_from_events(events + [event], now=now)
        self._atomic_write(current)
        return {"status": "RECORDED", "event_id": event_id, "version": version}

    def _current_from_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "version": event["version"],
            "status": "BLOCKED" if _is_failure(event["event_type"]) else "ACTIVE",
            "updated_at": event["recorded_at"],
            "expires_at": event["expires_at"],
            "provenance": {key: event[key] for key in ("event_id", "event_type", "source", "source_ref", "occurred_at", "recorded_at")},
            "state": event["payload"],
            "safety": _gates(),
        }

    def _current_from_events(
        self, events: list[Mapping[str, Any]], *, now: datetime | None = None,
    ) -> dict[str, Any]:
        latest = events[-1]
        current = self._current_from_event(latest)
        now = (now or self.clock()).astimezone(timezone.utc)
        domains = {}
        for domain in RECOVERY_DOMAINS:
            candidates = [item for item in events if _event_domain(item) == domain]
            if not candidates:
                domains[domain] = {
                    "status": "UNKNOWN",
                    "acceptance": "UNVERIFIED",
                    "last_known": None,
                    "provenance": None,
                    "ttl": None,
                }
                continue
            event = candidates[-1]
            expired = _parse_timestamp(event["expires_at"]) <= now
            failed = _is_failure(event["event_type"])
            domains[domain] = {
                "status": "EXPIRED" if expired else ("BLOCKED" if failed else "ACTIVE"),
                "acceptance": "UNVERIFIED",
                "last_known": event["payload"],
                "provenance": {key: event[key] for key in (
                    "event_id", "event_type", "source", "source_ref", "occurred_at", "recorded_at",
                )},
                "ttl": {
                    "recorded_at": event["recorded_at"],
                    "expires_at": event["expires_at"],
                    "expired": expired,
                },
            }
        current["domains"] = domains
        return current
    def read(self) -> dict[str, Any]:
        try:
            events = self._read_events()
            current = json.loads(self.state_path.read_text(encoding="utf-8"))
            if current.get("schema_version") != SCHEMA_VERSION:
                raise ContextManagerError("schema version mismatch")
            if (events and current.get("version") != events[-1].get("version")) or (not events and current):
                raise ContextManagerError("current state does not match event log")
            _parse_timestamp(current["expires_at"])
            _parse_timestamp(current["updated_at"])
            if current.get("safety") != _gates():
                raise ContextManagerError("safety contract mismatch")
            now = self.clock().astimezone(timezone.utc)
            if events:
                expected_domains = self._current_from_events(events, now=now)["domains"]
                actual_domains = current.get("domains")
                if not isinstance(actual_domains, dict) or set(actual_domains) != set(expected_domains):
                    raise ContextManagerError("domain snapshot does not match event log")
                for domain, expected in expected_domains.items():
                    actual = actual_domains[domain]
                    expected_ttl = expected.get("ttl")
                    actual_ttl = actual.get("ttl") if isinstance(actual, dict) else None
                    if not isinstance(actual, dict) or any(
                        actual.get(key) != expected.get(key)
                        for key in ("last_known", "provenance", "acceptance")
                    ) or actual_ttl != expected_ttl and (
                        expected_ttl is None or not isinstance(actual_ttl, dict)
                        or actual_ttl.get("recorded_at") != expected_ttl.get("recorded_at")
                        or actual_ttl.get("expires_at") != expected_ttl.get("expires_at")
                    ):
                        raise ContextManagerError("domain snapshot does not match event log")
                current["domains"] = expected_domains
            if _parse_timestamp(current["expires_at"]) <= now:
                current["status"] = "EXPIRED"
            return current
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ContextManagerError) as exc:
            return {"schema_version": SCHEMA_VERSION, "status": "BLOCKED", "reason": "STATE_UNAVAILABLE", "detail": type(exc).__name__, "safety": _gates()}

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        result = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if not isinstance(item, dict) or item.get("schema_version") != SCHEMA_VERSION:
                raise ContextManagerError("event log is invalid")
            required = {"version", "event_id", "event_type", "source", "occurred_at", "recorded_at", "expires_at", "fingerprint", "payload"}
            if not required.issubset(item) or item["source"] not in KNOWN_SOURCES or not isinstance(item["payload"], dict):
                raise ContextManagerError("event log fields are invalid")
            if item["payload"] != _sanitize(item["payload"]) or item["fingerprint"] != _fingerprint(item["payload"]):
                raise ContextManagerError("event log integrity check failed")
            for timestamp in (item["occurred_at"], item["recorded_at"], item["expires_at"]):
                _parse_timestamp(timestamp)
            result.append(item)
        versions = [item.get("version") for item in result]
        if versions != list(range(1, len(versions) + 1)):
            raise ContextManagerError("event log version sequence is invalid")
        return result

    def _atomic_write(self, value: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="context-state-", suffix=".tmp", dir=self.state_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def default_store() -> ContextManagerStore:
    state = os.environ.get(STATE_PATH_ENV, "").strip()
    events = os.environ.get(EVENTS_PATH_ENV, "").strip()
    if not state:
        state = str(Path(os.environ.get("PROGRAMDATA", "/run")) / "stock-razor" / "context-manager" / "current.json")
    return ContextManagerStore(state, events or None)


def record_if_configured(**kwargs: Any) -> dict[str, Any] | None:
    if not os.environ.get(STATE_PATH_ENV, "").strip():
        return None
    return default_store().record(**kwargs)


def _is_failure(event_type: str) -> bool:
    normalized = event_type.lower()
    return normalized.startswith("failure") or normalized.endswith("_failed") or normalized in {"ci_failed", "deployment_failed"}


def _event_domain(event: Mapping[str, Any]) -> str:
    event_type = str(event.get("event_type", "")).lower()
    source = str(event.get("source", "")).lower()
    if source == "ci" or event_type.startswith("ci_"):
        return "ci"
    if source == "deployment" or event_type.startswith("deployment_"):
        return "deploy"
    if source == "radar" or event_type.startswith("radar_"):
        return "radar"
    if event_type.startswith("pr_") or event_type.startswith("pull_request"):
        return "pr"
    if "blocker" in event_type:
        return "blockers"
    if "priorit" in event_type:
        return "priorities"
    return "blockers" if _is_failure(event_type) else "priorities"
def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

"""Local SQLite reservation fence for paid TickFlow history requests.

RESEARCH ONLY. No TickFlow SDK, credentials, billing policy or HTTP calls.
Shared only among callers using the *same local database file*; NOT a
multi-host/AWS distributed reservation mechanism.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")


@dataclass(frozen=True)
class ReservationDecision:
    status: str
    reason: str
    reserved_units: int = 0
    paid_transport_calls: int = 0
    source_arbiter_admission: str = "BLOCKED"
    radar_admission: str = "BLOCKED"
    paper_auto_ready: bool = False
    live_trade: bool = False


def initialize_offline_ledger(
    path: str | Path, *,
    request_units: int,
    quota_units: int,
    enabled: bool = False,
) -> None:
    """Provision a *new* isolated test ledger; never overwrites old balances."""
    if (
        type(request_units) is not int or request_units < 0
        or type(quota_units) is not int or quota_units < 0
        or type(enabled) is not bool
    ):
        raise ValueError("invalid offline test ledger")
    path = Path(path)
    if path.exists():
        raise FileExistsError("ledger already exists; refusing balance reset")
    with sqlite3.connect(path, timeout=5) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "CREATE TABLE budget "
            "(singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
            " enabled INTEGER NOT NULL, remaining INTEGER NOT NULL,"
            " quota INTEGER NOT NULL)"
        )
        db.execute(
            "CREATE TABLE reservations "
            "(request_id TEXT PRIMARY KEY, units INTEGER NOT NULL)"
        )
        db.execute(
            "INSERT INTO budget VALUES (1, ?, ?, ?)",
            (int(enabled), request_units, quota_units),
        )


def reserve_local_request(
    path: str | Path, *, request_id: str, units: int = 1,
) -> ReservationDecision:
    """Atomically reserve once. No reserve implies no right to call a provider."""
    if not isinstance(request_id, str) or _IDENTIFIER.fullmatch(request_id) is None:
        return ReservationDecision("BLOCKED", "INVALID_REQUEST_ID")
    if type(units) is not int or units <= 0:
        return ReservationDecision("BLOCKED", "INVALID_UNITS")
    try:
        # mode=rw deliberately refuses to create a missing approval ledger.
        db = sqlite3.connect(
            Path(path).resolve().as_uri() + "?mode=rw", uri=True,
            isolation_level=None, timeout=5,
        )
    except (OSError, sqlite3.Error, ValueError):
        return ReservationDecision("UNKNOWN", "LEDGER_UNAVAILABLE")
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT enabled, remaining, quota FROM budget WHERE singleton=1"
        ).fetchone()
        if row is None or any(type(x) is not int or x < 0 for x in row):
            db.execute("ROLLBACK")
            return ReservationDecision("UNKNOWN", "LEDGER_STATE_UNKNOWN")
        enabled, remaining, quota = row
        if enabled != 1:
            db.execute("ROLLBACK")
            return ReservationDecision("BLOCKED", "LEDGER_DISABLED")
        if db.execute(
            "SELECT 1 FROM reservations WHERE request_id=?", (request_id,)
        ).fetchone():
            db.execute("ROLLBACK")
            return ReservationDecision("BLOCKED", "REQUEST_ALREADY_RESERVED")
        if remaining < units or quota < units:
            db.execute("ROLLBACK")
            return ReservationDecision("BLOCKED", "QUOTA_OR_BUDGET_EXHAUSTED")
        db.execute(
            "UPDATE budget SET remaining=?, quota=? WHERE singleton=1",
            (remaining - units, quota - units),
        )
        db.execute(
            "INSERT INTO reservations(request_id, units) VALUES (?, ?)",
            (request_id, units),
        )
        db.execute("COMMIT")
        return ReservationDecision("RESERVED_LOCAL_ONLY", "LOCAL_LEDGER_RESERVED", units)
    except sqlite3.Error:
        try:
            db.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return ReservationDecision("UNKNOWN", "LEDGER_TRANSACTION_UNKNOWN")
    finally:
        db.close()

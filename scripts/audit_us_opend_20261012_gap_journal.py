#!/usr/bin/env python3
"""Finite, read-only timeline audit for the 2026-10-12 US K1M common gap.

Read the EC2 journal locally; emit only fixed status enums and normalized UTC
systemd-manager timestamps. Never expose MESSAGE, journal logs, provider bars,
account/order identities, or credentials. Correlation is NOT proof of causality.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import subprocess
from typing import Iterable

UNIT = "stock-razor-us-livefeed.service"
START = datetime(2026, 10, 12, 14, 57, tzinfo=timezone.utc)
END = datetime(2026, 10, 12, 15, 2, tzinfo=timezone.utc)
MAX_RECORDS = 500
MAX_JOURNAL_BYTES = 600_000
MANAGER_ACTION = re.compile(r"^\s*(Stopping|Stopped|Starting|Started)\b", re.IGNORECASE)


def empty_result(reason: str) -> dict:
    allowed = {
        "JOURNAL_UNAVAILABLE", "NO_MANAGER_EVENTS_OBSERVED",
        "BOUND_EXCEEDED", "INVALID_RECORD", "MANAGER_EVENTS_INCOMPLETE",
    }
    return {
        "schema": "stock_razor_opend_gap_restart_journal_audit_v1",
        "time_window_utc": "2026-10-12T14:57:00Z/2026-10-12T15:02:00Z",
        "source": "LOCAL_EC2_SYSTEMD_JOURNAL_ONLY",
        "status": "NOT_VERIFIED",
        "reason": reason if reason in allowed else "JOURNAL_UNAVAILABLE",
        "manager_stops_utc": [],
        "manager_starts_utc": [],
        "manager_restart_pair": "NOT_VERIFIED",
        "missing_provider_bar": "NOT_VERIFIED",
        "provider_delivery": "NOT_VERIFIED",
        "causal_attribution": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "paper_auto_ready": "NO",
        "live_trade": "NO",
        "trade_execution": "NO",
    }


def _parse_entry(line: str) -> tuple[str, str] | None:
    try:
        entry = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(entry, dict):
        return None
    # The PID-1 systemd manager, not similarly-worded service stdout.
    if str(entry.get("_PID")) != "1" or entry.get("SYSLOG_IDENTIFIER") != "systemd":
        return None
    message = entry.get("MESSAGE")
    if not isinstance(message, str):
        return None
    # journalctl -u itself selects the exact systemd unit. Enforce metadata
    # unit identity again where available.
    identified = entry.get("UNIT") or entry.get("OBJECT_SYSTEMD_UNIT")
    if identified is not None and identified != UNIT:
        return None
    match = MANAGER_ACTION.match(message)
    if not match:
        return None
    if identified is None and UNIT not in message and "US LiveFeed" not in message:
        return None
    raw = entry.get("__REALTIME_TIMESTAMP")
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{16}", raw):
        return None
    try:
        instant = datetime.fromtimestamp(int(raw) / 1_000_000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    if not START <= instant <= END:
        return None
    return match.group(1).upper(), instant.isoformat(timespec="seconds").replace("+00:00", "Z")


def classify_journal_lines(lines: Iterable[str], *, truncated: bool = False) -> dict:
    result = empty_result("NO_MANAGER_EVENTS_OBSERVED")
    if truncated:
        result["reason"] = "BOUND_EXCEEDED"
        return result
    stops: list[str] = []
    starts: list[str] = []
    count = 0
    for line in lines:
        count += 1
        if count > MAX_RECORDS:
            return empty_result("BOUND_EXCEEDED")
        if not isinstance(line, str):
            return empty_result("INVALID_RECORD")
        item = _parse_entry(line)
        if item is None:
            continue
        action, stamp = item
        if action in ("STOPPING", "STOPPED"):
            stops.append(stamp)
        elif action in ("STARTING", "STARTED"):
            starts.append(stamp)
    result["manager_stops_utc"] = sorted(set(stops))[:10]
    result["manager_starts_utc"] = sorted(set(starts))[:10]
    if not stops and not starts:
        return result
    result["reason"] = "MANAGER_EVENTS_INCOMPLETE"
    if any(stop <= start for stop in stops for start in starts):
        result["status"] = "RESTART_SEQUENCE_OBSERVED"
        result["manager_restart_pair"] = "OBSERVED"
        result["reason"] = None
    return result


def run_audit() -> dict:
    command = [
        "journalctl", "--utc", "--output=json", "--no-pager", "--quiet",
        "--since=2026-10-12 14:57:00 UTC",
        "--until=2026-10-12 15:02:00 UTC",
        "--lines=500", "-u", UNIT,
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return empty_result("JOURNAL_UNAVAILABLE")
    if completed.returncode != 0:
        return empty_result("JOURNAL_UNAVAILABLE")
    if len(completed.stdout.encode("utf-8", errors="replace")) > MAX_JOURNAL_BYTES:
        return empty_result("BOUND_EXCEEDED")
    lines = completed.stdout.splitlines()
    # A full -n window can omit earlier restart evidence; fail closed.
    return classify_journal_lines(lines, truncated=len(lines) >= MAX_RECORDS)


def main() -> int:
    print(json.dumps(run_audit(), sort_keys=True, separators=(",", ":")))
    # A missing/rotated journal is a valid NOT_VERIFIED audit outcome,
    # never a PASS or claim of healthy provider data.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

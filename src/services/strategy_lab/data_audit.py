"""Fail-closed audit for offline OHLCV replay inputs."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REQUIRED_COLUMNS = {
    "time_key",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "symbol",
    "source",
    "timezone",
    "session",
    "closed_bar_evidence",
    "provider_finality",
    "calendar",
}


def _parse_timestamp(value: str) -> datetime:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("timestamps must include an explicit timezone")
    return timestamp.astimezone(timezone.utc)


def _status(values: list[str], verified: str, unknown: str = "UNKNOWN") -> str:
    if values and all(value == verified for value in values):
        return "PASS"
    if not values or any(value in {"", "UNKNOWN", "NOT_VERIFIED"} for value in values):
        return unknown
    return "FAIL"


def audit_csv(path: str | Path, *, now: datetime | None = None) -> dict[str, Any]:
    source = Path(path)
    raw = source.read_bytes()
    manifest_path = source.with_suffix(source.suffix + ".manifest.json")
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded
        except (OSError, json.JSONDecodeError):
            manifest = {}
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        missing = sorted(REQUIRED_COLUMNS - fields)
        rows = list(reader)

    timestamps: list[datetime] = []
    ohlcv_errors: list[int] = []
    parse_errors: list[int] = []
    symbols: list[str] = []
    sources: list[str] = []
    finality: list[str] = []
    closure: list[str] = []
    calendars: list[str] = []
    timezones: list[str] = []
    for index, row in enumerate(rows, start=2):
        symbols.append(row.get("symbol", ""))
        sources.append(row.get("source", ""))
        finality.append(row.get("provider_finality", "UNKNOWN"))
        closure.append(row.get("closed_bar_evidence", "UNKNOWN"))
        calendars.append(row.get("calendar", ""))
        timezones.append(row.get("timezone", ""))
        try:
            timestamps.append(_parse_timestamp(row["time_key"]))
            values = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}
            if not (
                all(value > 0 for key, value in values.items() if key != "volume")
                and values["volume"] >= 0
                and values["high"] >= max(values["open"], values["close"])
                and values["low"] <= min(values["open"], values["close"])
            ):
                ohlcv_errors.append(index)
        except (KeyError, TypeError, ValueError):
            parse_errors.append(index)

    duplicate_timestamps = len(timestamps) - len(set(timestamps))
    out_of_order = sum(left >= right for left, right in zip(timestamps, timestamps[1:]))
    source_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    rows_hash = "sha256:" + hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    observed_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    latest = max(timestamps) if timestamps else None
    age_seconds = (observed_now - latest).total_seconds() if latest else None
    freshness = "UNKNOWN" if age_seconds is None else "STALE" if age_seconds > 86400 else "FRESH"
    structural = not missing and bool(rows) and not parse_errors and not ohlcv_errors
    chronology = structural and duplicate_timestamps == 0 and out_of_order == 0
    lineage = structural and all(symbols) and all(sources)
    timezone_status = "PASS" if structural and timestamps else "UNKNOWN"
    dst_status = "UNKNOWN"
    if structural and timestamps and timezones and all(timezones) and len(set(timezones)) == 1:
        try:
            zone = ZoneInfo(timezones[0])
            dst_status = "PASS" if all(timestamp.astimezone(zone).tzinfo == zone for timestamp in timestamps) else "FAIL"
        except Exception:
            dst_status = "UNKNOWN"
    calendar_status = "NOT_VERIFIED"
    if structural and calendars and len(set(calendars)) == 1 and calendars[0] == "XNYS":
        try:
            import exchange_calendars as xcals
            sessions = xcals.get_calendar("XNYS").sessions_in_range(
                min(timestamp.date() for timestamp in timestamps),
                max(timestamp.date() for timestamp in timestamps),
            )
            observed_dates = {timestamp.date().isoformat() for timestamp in timestamps}
            calendar_status = "PASS" if observed_dates.issubset({item.date().isoformat() for item in sessions}) else "FAIL"
        except Exception:
            calendar_status = "UNKNOWN"
    finality_status = _status(finality, "VERIFIED")
    closure_status = _status(closure, "VERIFIED")
    raw_payload_hash = manifest.get("raw_payload_sha256")
    raw_payload_path = manifest.get("raw_payload_path")
    payload_status = "UNKNOWN"
    if isinstance(raw_payload_hash, str) and re.fullmatch(r"[0-9a-f]{64}", raw_payload_hash) and isinstance(raw_payload_path, str):
        candidate = Path(raw_payload_path)
        if not candidate.is_absolute():
            candidate = source.parent / candidate
        if candidate.is_file():
            observed_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
            payload_status = "PASS" if observed_hash == raw_payload_hash else "FAIL"
    replay_eligibility = (
        "PASS"
        if chronology and lineage and timezone_status == "PASS" and calendar_status == "PASS"
        and dst_status == "PASS" and finality_status == "PASS" and closure_status == "PASS"
        and payload_status == "PASS"
        else "BLOCKED"
    )
    return {
        "schema_version": "stock-razor-vibe-data-audit-v0.6",
        "status": "RESEARCH_ONLY",
        "path": str(source),
        "symbol": symbols[0] if symbols and len(set(symbols)) == 1 else "MIXED_OR_UNKNOWN",
        "rows": len(rows),
        "time_range": {"first_utc": min(timestamps).isoformat() if timestamps else None, "last_utc": latest.isoformat() if latest else None},
        "hashes": {"source_file": source_hash, "rows": rows_hash},
        "checks": {
            "required_columns": "PASS" if not missing else "FAIL",
            "missing_columns": missing,
            "ohlcv": "PASS" if structural else "FAIL",
            "parse_errors": parse_errors,
            "ohlcv_error_rows": ohlcv_errors,
            "timezone": timezone_status,
            "dst": dst_status,
            "trading_calendar": calendar_status,
            "chronology": "PASS" if chronology else "FAIL",
            "duplicate_timestamps": duplicate_timestamps,
            "out_of_order_pairs": out_of_order,
            "bar_closure": closure_status,
            "provider_finality": finality_status,
            "source_lineage": "PASS" if lineage else "UNKNOWN",
            "raw_payload_hash": payload_status,
            "manifest": "PASS" if manifest else "UNKNOWN",
            "freshness": freshness,
            "age_seconds": age_seconds,
        },
        "historical_replay": {"eligibility": replay_eligibility, "freshness_is_not_eligibility": True},
        "safety": {"radar_admission": "BLOCKED", "trade_execution": "NO", "paper_auto_ready": False},
    }

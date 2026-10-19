"""Fail-closed audit for offline OHLCV replay inputs."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    for index, row in enumerate(rows, start=2):
        symbols.append(row.get("symbol", ""))
        sources.append(row.get("source", ""))
        finality.append(row.get("provider_finality", "UNKNOWN"))
        closure.append(row.get("closed_bar_evidence", "UNKNOWN"))
        calendars.append(row.get("calendar", ""))
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
    calendar_status = "PASS" if structural and all(calendars) else "NOT_VERIFIED"
    finality_status = _status(finality, "VERIFIED")
    closure_status = _status(closure, "VERIFIED")
    replay_eligibility = (
        "PASS"
        if chronology and lineage and timezone_status == "PASS" and calendar_status == "PASS"
        and finality_status == "PASS" and closure_status == "PASS"
        else "BLOCKED"
    )
    return {
        "schema_version": "stock-razor-vibe-data-audit-v0.5",
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
            "dst": "NOT_VERIFIED",
            "trading_calendar": calendar_status,
            "chronology": "PASS" if chronology else "FAIL",
            "duplicate_timestamps": duplicate_timestamps,
            "out_of_order_pairs": out_of_order,
            "bar_closure": closure_status,
            "provider_finality": finality_status,
            "source_lineage": "PASS" if lineage else "UNKNOWN",
            "freshness": freshness,
            "age_seconds": age_seconds,
        },
        "historical_replay": {"eligibility": replay_eligibility, "freshness_is_not_eligibility": True},
        "safety": {"radar_admission": "BLOCKED", "trade_execution": "NO", "paper_auto_ready": False},
    }

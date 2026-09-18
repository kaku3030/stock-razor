#!/usr/bin/env python3
"""Fail-closed validation for a captured research universe.

This validates the recorded evidence boundary only.  It does not approve a
provider for production and does not infer corporate-action or survivorship
correctness beyond the fields present in the capture contract.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import date, datetime
from pathlib import Path


REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume")
CAPTURED_NOT_APPROVED = "CAPTURED_NOT_APPROVED"
CAPTURE_BLOCKED = "CAPTURE_BLOCKED"
MISSING_UNAVAILABLE = "MISSING_UNAVAILABLE"
RESULT_KEYS = (CAPTURED_NOT_APPROVED, CAPTURE_BLOCKED, MISSING_UNAVAILABLE)


def _read_manifest(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid manifest: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be an object: {path}")
    return payload


def _validate_file(csv_path: Path, manifest_path: Path, *, market: str, symbol: str, source_id: str) -> int:
    if not csv_path.is_file():
        raise ValueError(f"missing capture CSV: {csv_path}")
    if not manifest_path.is_file():
        raise ValueError(f"missing capture manifest: {manifest_path}")
    manifest = _read_manifest(manifest_path)
    if manifest.get("status") != CAPTURED_NOT_APPROVED:
        raise ValueError(f"capture is not recorded evidence ({csv_path}): {manifest.get('status')!r}")
    if manifest.get("market") != market or manifest.get("source_id") != source_id:
        raise ValueError(f"manifest source mismatch: {manifest_path}")
    retrieved_at = manifest.get("retrieved_at")
    if not isinstance(retrieved_at, str):
        raise ValueError(f"manifest retrieved_at missing: {manifest_path}")
    try:
        parsed_retrieved_at = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"manifest retrieved_at invalid: {manifest_path}") from exc
    if parsed_retrieved_at.tzinfo is None:
        raise ValueError(f"manifest retrieved_at must include timezone: {manifest_path}")
    digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    if manifest.get("raw_sha256") != digest:
        raise ValueError(f"raw_sha256 mismatch: {csv_path}")

    rows = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REQUIRED_COLUMNS:
            raise ValueError(f"unexpected columns: {csv_path}")
        for row_number, row in enumerate(reader, start=2):
            if row.get("symbol") != symbol:
                raise ValueError(f"symbol mismatch at row {row_number}: {csv_path}")
            try:
                day = date.fromisoformat(row["date"])
                values = {name: float(row[name]) for name in REQUIRED_COLUMNS[2:]}
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"malformed row {row_number}: {csv_path}") from exc
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError(f"non-finite OHLCV at row {row_number}: {csv_path}")
            if min(values["open"], values["high"], values["low"], values["close"]) <= 0:
                raise ValueError(f"non-positive price at row {row_number}: {csv_path}")
            if values["high"] < max(values["open"], values["low"], values["close"]):
                raise ValueError(f"high below observed price at row {row_number}: {csv_path}")
            if values["low"] > min(values["open"], values["high"], values["close"]):
                raise ValueError(f"low above observed price at row {row_number}: {csv_path}")
            if values["volume"] < 0:
                raise ValueError(f"negative volume at row {row_number}: {csv_path}")
            rows.append(day)
    if len(rows) < 2:
        raise ValueError(f"capture must contain at least two rows: {csv_path}")
    if rows != sorted(rows) or len(set(rows)) != len(rows):
        raise ValueError(f"dates must be unique and chronological: {csv_path}")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--evidence-report", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    errors: list[str] = []
    validated: list[dict[str, object]] = []
    results: list[dict[str, object]] = []
    result_counts = {key: 0 for key in RESULT_KEYS}
    for market, definition in config.get("markets", {}).items():
        source_id = definition.get("source_id")
        for symbol in definition.get("symbols", []):
            safe_symbol = symbol.replace(".", "_")
            csv_path = args.input_dir / f"{market}_{safe_symbol}.csv"
            manifest_path = Path(f"{csv_path}.manifest.json")
            csv_present = csv_path.is_file()
            manifest_present = manifest_path.is_file()
            result = MISSING_UNAVAILABLE
            result_errors: list[str] = []
            count: int | None = None

            if manifest_present:
                try:
                    manifest = _read_manifest(manifest_path)
                except ValueError as exc:
                    manifest = None
                    result_errors.append(str(exc))
                if manifest is not None and manifest.get("status") == CAPTURE_BLOCKED:
                    result = CAPTURE_BLOCKED
                    error = manifest.get("error")
                    if isinstance(error, str) and error:
                        result_errors.append(error)
                    if csv_present:
                        result_errors.append("CAPTURE_BLOCKED must not have a capture CSV")
                elif not csv_present:
                    result_errors.append(f"missing capture CSV: {csv_path}")
                elif manifest is not None and manifest.get("status") == CAPTURED_NOT_APPROVED:
                    result = CAPTURED_NOT_APPROVED
                    try:
                        count = _validate_file(
                            csv_path,
                            manifest_path,
                            market=market,
                            symbol=symbol,
                            source_id=source_id,
                        )
                    except ValueError as exc:
                        result_errors.append(str(exc))
                else:
                    result_errors.append(f"unsupported or missing capture status: {manifest_path}")
            else:
                if not csv_present:
                    result_errors.append(f"missing capture CSV and manifest: {csv_path}")
                else:
                    result_errors.append(f"missing capture manifest: {manifest_path}")

            result_counts[result] += 1
            entry: dict[str, object] = {
                "market": market,
                "symbol": symbol,
                "result": result,
                "csv_present": csv_present,
                "manifest_present": manifest_present,
            }
            if count is not None:
                entry["rows"] = count
                validated.append({"market": market, "symbol": symbol, "rows": count})
            if result_errors:
                entry["errors"] = result_errors
                errors.extend(f"{symbol}: {item}" for item in result_errors)
            results.append(entry)
    report = {
        "schema": "radar-research-universe-evidence-v0.1",
        "status": "INVALID" if errors or result_counts[CAPTURED_NOT_APPROVED] != len(results) else "VALIDATED",
        "pit_status": "RECORDED_CAPTURE_ONLY",
        "approval_required": True,
        "symbol_count": len(validated),
        "captures": validated,
        "results": results,
        "result_counts": result_counts,
        "errors": errors,
    }
    if args.evidence_report:
        args.evidence_report.parent.mkdir(parents=True, exist_ok=True)
        args.evidence_report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if errors or result_counts[CAPTURED_NOT_APPROVED] != len(results):
        print(json.dumps(report, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

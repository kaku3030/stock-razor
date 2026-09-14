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
from datetime import date
from pathlib import Path


REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume")


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
    if manifest.get("status") != "CAPTURED_NOT_APPROVED":
        raise ValueError(f"capture is not recorded evidence ({csv_path}): {manifest.get('status')!r}")
    if manifest.get("market") != market or manifest.get("source_id") != source_id:
        raise ValueError(f"manifest source mismatch: {manifest_path}")
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
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    errors: list[str] = []
    validated: list[dict[str, object]] = []
    for market, definition in config.get("markets", {}).items():
        source_id = definition.get("source_id")
        for symbol in definition.get("symbols", []):
            safe_symbol = symbol.replace(".", "_")
            csv_path = args.input_dir / f"{market}_{safe_symbol}.csv"
            manifest_path = Path(f"{csv_path}.manifest.json")
            try:
                count = _validate_file(csv_path, manifest_path, market=market, symbol=symbol, source_id=source_id)
                validated.append({"market": market, "symbol": symbol, "rows": count})
            except ValueError as exc:
                errors.append(str(exc))
    if errors:
        print(json.dumps({"status": "INVALID", "errors": errors, "validated": validated}, sort_keys=True))
        return 2
    print(json.dumps({"status": "VALIDATED", "symbol_count": len(validated), "captures": validated}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

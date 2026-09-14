#!/usr/bin/env python3
"""Compare two frozen captures without polling either provider.

The comparison is a research-quality diagnostic, not an approval decision.
Different adjustment policies or insufficient date overlap fail closed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


PRICE_FIELDS = ("open", "high", "low", "close")


def _load(path: Path, manifest_path: Path) -> tuple[dict, dict[str, dict[str, float]]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "CAPTURED_NOT_APPROVED":
        raise ValueError(f"capture is not recorded evidence: {manifest.get('status')!r}")
    if manifest.get("raw_sha256") != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError(f"raw_sha256 mismatch: {path}")
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "date", *PRICE_FIELDS, "volume"}
        if set(reader.fieldnames or ()) != required:
            raise ValueError(f"unexpected columns: {path}")
        rows: dict[str, dict[str, float]] = {}
        for row in reader:
            if row["date"] in rows:
                raise ValueError(f"duplicate date in {path}: {row['date']}")
            values = {field: float(row[field]) for field in (*PRICE_FIELDS, "volume")}
            if not all(math.isfinite(value) for value in values.values()):
                raise ValueError(f"non-finite row in {path}: {row['date']}")
            rows[row["date"]] = values
    return manifest, rows


def compare(left_path: Path, left_manifest_path: Path, right_path: Path, right_manifest_path: Path, *, minimum_overlap: float, maximum_price_rel_diff: float, maximum_volume_rel_diff: float) -> dict:
    left_manifest, left = _load(left_path, left_manifest_path)
    right_manifest, right = _load(right_path, right_manifest_path)
    if left_manifest.get("source_id") == right_manifest.get("source_id"):
        raise ValueError("cross-source comparison requires different source_id values")
    if left_manifest.get("market") != right_manifest.get("market"):
        raise ValueError("captures must belong to the same market")
    if left_manifest.get("adjustment", "unadjusted") != right_manifest.get("adjustment", "unadjusted"):
        raise ValueError("adjustment semantics differ")
    overlap = sorted(set(left) & set(right))
    denominator = max(len(left), len(right))
    overlap_ratio = len(overlap) / denominator if denominator else 0.0
    if overlap_ratio < minimum_overlap:
        return {"status": "UNKNOWN", "reason": "INSUFFICIENT_DATE_OVERLAP", "overlap": len(overlap), "overlap_ratio": overlap_ratio}
    price_diffs = []
    volume_ratios = []
    for day in overlap:
        for field in PRICE_FIELDS:
            base = left[day][field]
            other = right[day][field]
            price_diffs.append(abs(other - base) / abs(base) if base else float("inf"))
        base_volume = left[day]["volume"]
        other_volume = right[day]["volume"]
        if base_volume > 0 and other_volume > 0:
            volume_ratios.append(other_volume / base_volume)
    max_price = max(price_diffs, default=float("inf"))
    # Providers may express volume in shares, lots, or contracts.  Accept a
    # stable multiplicative unit factor, but still reject day-varying drift.
    volume_scale = sorted(volume_ratios)[len(volume_ratios) // 2] if volume_ratios else 1.0
    normalized_volume_diffs = [abs(ratio / volume_scale - 1.0) for ratio in volume_ratios]
    max_volume = max(normalized_volume_diffs, default=float("inf"))
    status = "VALIDATED" if max_price <= maximum_price_rel_diff and max_volume <= maximum_volume_rel_diff else "DIVERGENT"
    return {"status": status, "left_source": left_manifest.get("source_id"), "right_source": right_manifest.get("source_id"), "overlap": len(overlap), "overlap_ratio": overlap_ratio, "max_price_relative_difference": max_price, "volume_scale_factor_right_over_left": volume_scale, "max_volume_relative_difference_after_scale": max_volume, "thresholds": {"minimum_overlap": minimum_overlap, "maximum_price_relative_difference": maximum_price_rel_diff, "maximum_volume_relative_difference": maximum_volume_rel_diff}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--left-csv", type=Path, required=True)
    parser.add_argument("--left-manifest", type=Path, required=True)
    parser.add_argument("--right-csv", type=Path, required=True)
    parser.add_argument("--right-manifest", type=Path, required=True)
    parser.add_argument("--minimum-overlap", type=float, default=0.95)
    parser.add_argument("--maximum-price-relative-difference", type=float, default=0.02)
    parser.add_argument("--maximum-volume-relative-difference", type=float, default=0.20)
    args = parser.parse_args()
    try:
        result = compare(args.left_csv, args.left_manifest, args.right_csv, args.right_manifest, minimum_overlap=args.minimum_overlap, maximum_price_rel_diff=args.maximum_price_relative_difference, maximum_volume_rel_diff=args.maximum_volume_relative_difference)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"status": "INVALID", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "VALIDATED" else 2


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fail-closed Round13 artifact inventory for Round14 cloud migration.

Stdlib-only. Does not fetch market data, trade, or infer missing inputs.
Usage: python tools/research/round14_artifact_gate.py --directory /private/round13
Exit: 0 complete and hash-verified; 2 incomplete or invalid.
"""
import argparse
import hashlib
import json
from pathlib import Path

REQUIRED = (
    "round13_report.md",
    "round13_status.json",
    "round13_artifact_manifest.sha256",
    "round13_trade_ledger.csv",
    "round13_portfolio_equity_curve.csv",
    "round13_regime_coverage.csv",
)
FORBIDDEN_STATUS = ("PASS", "READY", "VERIFIED")


def verify(directory: Path) -> dict:
    findings = {"directory": str(directory), "required": {}, "hashes": {}, "gate": "BLOCKED"}
    for name in REQUIRED:
        p = directory / name
        findings["required"][name] = p.is_file() and p.stat().st_size > 0
    manifest = directory / "round13_artifact_manifest.sha256"
    if manifest.is_file():
        for line in manifest.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split(maxsplit=1)
            if len(fields) != 2 or len(fields[0]) != 64:
                findings["hashes"][line] = False
                continue
            expected, filename = fields
            filename = filename.lstrip("*").replace("\\", "/")
            target = (directory / filename).resolve()
            # Prevent manifest entries escaping the provided directory.
            if not target.is_relative_to(directory.resolve()) or not target.is_file():
                findings["hashes"][filename] = False
                continue
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            findings["hashes"][filename] = actual.lower() == expected.lower()
    findings["inventory_complete"] = all(findings["required"].values())
    findings["manifest_valid"] = bool(findings["hashes"]) and all(findings["hashes"].values())
    # Even with verified output artifacts, historical OHLC inputs and engine source
    # must be verified independently before any cloud parity claim.
    findings["engine_source_verified"] = False
    findings["ohlc_inputs_verified"] = False
    findings["gate"] = "BLOCKED"
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    result = verify(args.directory)
    output = json.dumps(result, ensure_ascii=False, indent=2)
    print(output)
    if args.json_out:
        args.json_out.write_text(output + "\n", encoding="utf-8")
    return 0 if result["inventory_complete"] and result["manifest_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

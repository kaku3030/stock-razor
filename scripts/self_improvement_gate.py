#!/usr/bin/env python3
"""STOCK RAZOR shared failure registry validation and duplicate-retry triage.

No provider/network/model calls, no filesystem writes and no gate promotions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / ".claude/skills/stock-razor-self-improvement/failure-registry.json"
SCHEMA = "stock_razor_cross_window_failure_registry_v1"
VALID_STATES = {"OPEN", "MITIGATED", "RESOLVED"}
VALID_SEVERITIES = {"P0", "P1", "P2"}
SHA = re.compile(r"^[0-9a-f]{40}$")
IDENT = re.compile(r"^[A-Z]{2,5}-[0-9]{3}$")
# Real error signatures include dotted tickers/endpoints (518880.SH, KLINES.GET).
TOKEN = re.compile(r"^[A-Z0-9_.]{2,64}$")
GITHUB = "https://github.com/kaku3030/stock-razor/"


class RegistryError(ValueError):
    """A malformed or untrusted shared failure registry."""


def load_registry(path: Path = REGISTRY, *, check_tests: bool = True) -> dict:
    """Strictly validate before any rule lookup, including absent/stale revisions."""
    try:
        if not path.is_file() or not 0 < path.stat().st_size <= 100_000:
            raise RegistryError("REGISTRY_MISSING_OR_OVERSIZED")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, RegistryError):
            raise
        raise RegistryError("REGISTRY_INVALID_JSON") from None
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise RegistryError("REGISTRY_SCHEMA_MISMATCH")
    if value.get("authority") != "kaku3030/stock-razor/main":
        raise RegistryError("REGISTRY_AUTHORITY_MISMATCH")
    observed = value.get("last_reconciled_utc")
    try:
        dt = datetime.fromisoformat(observed.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None or dt > datetime.now(timezone.utc):
            raise ValueError("not an already-observed UTC revision")
    except (TypeError, AttributeError, ValueError):
        raise RegistryError("REGISTRY_TIMESTAMP_INVALID") from None
    records = value.get("records")
    if not isinstance(records, list) or not 1 <= len(records) <= 200:
        raise RegistryError("REGISTRY_RECORDS_INVALID")
    seen = set()
    required = {
        "id", "owner", "severity", "signature_tokens", "status", "diagnosis",
        "evidence_url", "regression_evidence", "mandatory_action", "repeat_policy",
    }
    for record in records:
        if not isinstance(record, dict) or set(record) != required:
            raise RegistryError("REGISTRY_RECORD_FIELDS")
        identifier = record["id"]
        if not isinstance(identifier, str) or not IDENT.fullmatch(identifier) or identifier in seen:
            raise RegistryError("REGISTRY_DUPLICATE_OR_INVALID_ID")
        seen.add(identifier)
        if record["owner"] not in {"Main Control", "OpenD", "TickFlow"}:
            raise RegistryError("REGISTRY_INVALID_OWNER")
        if record["severity"] not in VALID_SEVERITIES or record["status"] not in VALID_STATES:
            raise RegistryError("REGISTRY_INVALID_ENUM")
        tokens = record["signature_tokens"]
        if (not isinstance(tokens, list) or not 1 <= len(tokens) <= 5
                or len(set(tokens)) != len(tokens)
                or any(not isinstance(item, str) or not TOKEN.fullmatch(item) for item in tokens)):
            raise RegistryError("REGISTRY_SIGNATURE_INVALID")
        for name in ("diagnosis", "mandatory_action"):
            text = record[name]
            if not isinstance(text, str) or not 12 <= len(text) <= 1200:
                raise RegistryError("REGISTRY_DESCRIPTION_INVALID")
        url = record["evidence_url"]
        if not isinstance(url, str) or not url.startswith(GITHUB) or len(url) > 350:
            raise RegistryError("REGISTRY_EVIDENCE_INVALID")
        test = record["regression_evidence"]
        if not isinstance(test, str) or len(test) > 200:
            raise RegistryError("REGISTRY_TEST_INVALID")
        if record["status"] == "RESOLVED" and test == "NOT_VERIFIED":
            raise RegistryError("REGISTRY_RESOLVED_WITHOUT_REGRESSION")
        if test != "NOT_VERIFIED":
            target = ROOT / test
            if not test.startswith("tests/") or ".." in Path(test).parts:
                raise RegistryError("REGISTRY_TEST_PATH_INVALID")
            if check_tests and not target.is_file():
                raise RegistryError("REGISTRY_TEST_NOT_FOUND")
        if record["repeat_policy"] != "STOP_ON_SAME_SHA_AND_NO_NEW_EVIDENCE":
            raise RegistryError("REGISTRY_REPEAT_POLICY_INVALID")
    return value


def classify(registry: dict, *, signature: str, sha: str,
             previous_sha: str | None = None) -> dict:
    """Same known signature on same verified SHA => STOP_DUPLICATE.

    The caller must verify that environment and probe arguments are unchanged
    before supplying previous_sha. A new SHA is NOT proof the bug is fixed.
    """
    if not SHA.fullmatch(sha) or (previous_sha is not None and not SHA.fullmatch(previous_sha)):
        raise RegistryError("REVISION_SHA_INVALID")
    if not isinstance(signature, str) or not 1 <= len(signature) <= 2000:
        raise RegistryError("SIGNATURE_INVALID")
    raw = signature.upper()
    matches = [r for r in registry["records"]
               if all(re.search(r"(?<![A-Z0-9_])" + re.escape(t) + r"(?![A-Z0-9_])", raw)
                      for t in r["signature_tokens"])]
    if not matches:
        return {"action": "UNKNOWN", "failure_ids": [],
                "reason": "NO_EXACT_REGISTERED_FAILURE_MATCH", "source_sha": sha}
    priority = {"P0": 0, "P1": 1, "P2": 2}
    matches.sort(key=lambda r: (priority[r["severity"]], r["id"]))
    active = [x for x in matches if x["status"] != "RESOLVED"]
    selected = active if active else matches
    repeated = previous_sha is not None and sha == previous_sha and bool(active)
    return {
        "action": "STOP_DUPLICATE" if repeated else "DIAGNOSE_OR_PATCH",
        "failure_ids": [x["id"] for x in selected],
        "reason": ("SAME_FAILURE_SAME_VERIFIED_SHA_NO_NEW_EVIDENCE" if repeated
                   else "KNOWN_FAILURE_REQUIRES_ROOT_CAUSE_OR_NEW_PROOF"),
        "source_sha": sha,
        "mandatory_actions": [x["mandatory_action"] for x in selected],
        "regression_evidence": [x["regression_evidence"] for x in selected],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--check-registry", action="store_true")
    command.add_argument("--status", action="store_true")
    command.add_argument("--brief", action="store_true")
    command.add_argument("--signature", type=str)
    parser.add_argument("--sha")
    parser.add_argument("--previous-sha")
    args = parser.parse_args(argv)
    try:
        registry = load_registry()
        if args.check_registry:
            result = {"status": "PASS", "schema": SCHEMA, "records": len(registry["records"])}
        elif args.brief:
            # Fast startup fingerprint: bounded data, no raw logs or probes.
            rows = registry["records"]
            result = {
                "status": "OBSERVED",
                "schema": SCHEMA,
                "revision": registry["last_reconciled_utc"],
                "count": len(rows),
                "open": sum(r["status"] == "OPEN" for r in rows),
                "mitigated": sum(r["status"] == "MITIGATED" for r in rows),
                "resolved": sum(r["status"] == "RESOLVED" for r in rows),
                "p0": [r["id"] for r in rows if r["severity"] == "P0"
                       and r["status"] != "RESOLVED"],
                "duplicate_retry_policy": "STOP_ON_SAME_SHA_AND_NO_NEW_EVIDENCE",
                "gate": "RESEARCH_ONLY",
                "cross_chat_delivery": "NOT_VERIFIED",
            }
        elif args.status:
            result = {"status": "OBSERVED", "schema": SCHEMA, "last_reconciled_utc":
                      registry["last_reconciled_utc"], "records":
                      [{"id": r["id"], "status": r["status"], "severity": r["severity"],
                        "owner": r["owner"]} for r in registry["records"]]}
        else:
            if args.sha is None:
                raise RegistryError("REVISION_SHA_REQUIRED")
            result = classify(registry, signature=args.signature, sha=args.sha,
                              previous_sha=args.previous_sha)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
        return 3 if result.get("action") == "STOP_DUPLICATE" else 0
    except RegistryError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

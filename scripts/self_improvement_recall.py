#!/usr/bin/env python3
"""Fast bounded bilingual associative retrieval from the canonical error registry.

This is READ-ONLY retrieval, NOT an AI diagnosis or an automated trade gate.
New errors without supported matches remain UNKNOWN and require evidence capture.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata

from scripts.self_improvement_gate import REGISTRY, ROOT, RegistryError, load_registry

ASSOCIATIONS = ROOT / ".claude/skills/stock-razor-self-improvement/associations.json"
SCHEMA = "stock_razor_error_association_v1"


class RecallError(ValueError):
    pass


def _norm(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def load_associations(path: Path = ASSOCIATIONS, registry: dict | None = None) -> dict:
    registry = registry if registry is not None else load_registry()
    try:
        file = Path(path)
        if not file.is_file() or not 0 < file.stat().st_size <= 100_000:
            raise RecallError("ASSOCIATIONS_MISSING_OR_OVERSIZED")
        mapping = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, RecallError):
            raise
        raise RecallError("ASSOCIATIONS_UNREADABLE") from None
    if (not isinstance(mapping, dict)
            or set(mapping) != {"schema", "scope", "authority", "semantics", "cases"}
            or mapping["schema"] != SCHEMA
            or mapping["scope"] != "STOCK_RAZOR_ONLY"
            or mapping["authority"] != "kaku3030/stock-razor/main"
            or not isinstance(mapping["semantics"], str)
            or len(mapping["semantics"]) < 30
            or not isinstance(mapping["cases"], list)
            or len(mapping["cases"]) > 200):
        raise RecallError("ASSOCIATIONS_SCHEMA_INVALID")
    registered = {r["id"] for r in registry["records"]}
    seen = set()
    for record in mapping["cases"]:
        if not isinstance(record, dict) or set(record) != {"id", "phrases", "related"}:
            raise RecallError("ASSOCIATIONS_FIELDS_INVALID")
        id_ = record["id"]
        if not isinstance(id_, str) or id_ not in registered or id_ in seen:
            raise RecallError("ASSOCIATIONS_UNKNOWN_OR_DUPLICATE_ID")
        seen.add(id_)
        phrases = record["phrases"]
        if (not isinstance(phrases, list) or not 2 <= len(phrases) <= 35
                or any(not isinstance(p, str) or not 2 <= len(p) <= 80 for p in phrases)
                or any(_norm(p) != _norm(p).strip() or not _norm(p) for p in phrases)
                or len({_norm(p) for p in phrases}) != len(phrases)):
            raise RecallError("ASSOCIATIONS_PHRASES_INVALID")
        links = record["related"]
        if (not isinstance(links, list) or len(links) > 8
                or any(not isinstance(x, str) or x not in registered or x == id_
                       for x in links)
                or len(set(links)) != len(links)):
            raise RecallError("ASSOCIATIONS_LINKS_INVALID")
    return mapping


def _contains(query: str, phrase: str) -> bool:
    """Prevent short English tokens ('CI', 'D1') from matching inside words."""
    normal = _norm(phrase)
    if not normal:
        return False
    if re.fullmatch(r"[a-z0-9_.-]+", normal):
        return re.search(r"(?<![a-z0-9_.-])" + re.escape(normal)
                         + r"(?![a-z0-9_.-])", query) is not None
    return normal in query


def recall(query: str, *, registry: dict, associations: dict,
           max_results: int = 4) -> dict:
    if not isinstance(query, str) or not 2 <= len(query) <= 1500:
        raise RecallError("RECALL_QUERY_INVALID")
    if type(max_results) is not int or not 1 <= max_results <= 8:
        raise RecallError("RECALL_LIMIT_INVALID")
    normalized = _norm(query)
    knowledge = {r["id"]: r for r in registry["records"]}
    hints = {x["id"]: x for x in associations["cases"]}
    matches = []
    for id_, record in knowledge.items():
        alias = hints.get(id_, {})
        keywords = list(dict.fromkeys(record["signature_tokens"] + alias.get("phrases", [])))
        present = [p for p in keywords if _contains(normalized, p)]
        if not present:
            continue
        # Longest/specific multi-part matches first. A generic D1 or CI tag
        # never counts as a verified diagnosis even if it ranks first.
        signatures = [p for p in present if p in record["signature_tokens"]]
        distinctive = [p for p in present if len(_norm(p)) >= 8 or any("\u4e00" <= c <= "\u9fff" for c in p)]
        score = 3 * len(signatures) + 2 * len(distinctive) + len(present)
        if record["status"] == "RESOLVED":
            score += 0  # Still relevant as a past fix, not proof in current environment.
        matches.append((score, id_, present))
    matches.sort(key=lambda row: (-row[0], row[1]))
    direct = []
    for score, id_, terms in matches[:max_results]:
        item = knowledge[id_]
        direct.append({
            "id": id_, "owner": item["owner"], "status": item["status"],
            "severity": item["severity"], "symptom_score": score,
            "matched_hints": terms[:6],
            "relationship": "SYMPTOM_SIMILARITY_NOT_PROVEN_ROOT_CAUSE",
            "prior_diagnosis": item["diagnosis"],
            "previous_evidence": item["evidence_url"],
            "suggested_next_nonduplicate_step": item["mandatory_action"],
            "regression_evidence": item["regression_evidence"],
        })
    linked = []
    used = {x["id"] for x in direct}
    for case in direct[:2]:
        for neighbour in hints.get(case["id"], {}).get("related", []):
            if neighbour in used:
                continue
            used.add(neighbour)
            other = knowledge[neighbour]
            linked.append({
                "id": neighbour, "via": case["id"], "status": other["status"],
                "relationship": "POSSIBLY_RELATED_NOT_PROVEN",
                "evidence": other["evidence_url"],
            })
            if len(linked) >= 4:
                break
    return {
        "schema": "stock_razor_associative_recall_v1",
        "status": "RELATED_CASES_FOUND" if direct else "UNKNOWN_NEW_CASE_NEEDS_RECEIPT",
        "verified_root_cause": False, "may_autonomously_trade": False,
        "automated_retry_permission": "NOT_GRANTED",
        "registry_revision": registry["last_reconciled_utc"],
        "source_scope": "LOCAL_REPOSITORY_SNAPSHOT_FETCH_CURRENT_MAIN_BEFORE_USE",
        "results": direct, "related_cases": linked,
        "next_step_if_unknown": "CAPTURE_SANITIZED_FAILURE_RECEIPT_THEN_DIAGNOSE"
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", type=str)
    parser.add_argument("--max-results", type=int, default=4)
    parser.add_argument("--check-associations", action="store_true")
    args = parser.parse_args(argv)
    try:
        reg = load_registry()
        mapping = load_associations(registry=reg)
        if args.check_associations:
            report = {"status": "PASS", "schema": SCHEMA,
                      "linked_cases": len(mapping["cases"]),
                      "registry_cases": len(reg["records"])}
        else:
            if args.query is None:
                raise RecallError("RECALL_QUERY_REQUIRED")
            report = recall(args.query, registry=reg, associations=mapping,
                            max_results=args.max_results)
        print(json.dumps(report, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (RecallError, RegistryError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

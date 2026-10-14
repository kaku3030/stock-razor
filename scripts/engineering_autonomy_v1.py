"""Fail-closed policy for the Engineering Autonomy V1 workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


MARKER = "AUTONOMY_CANDIDATE=LOW_RISK"
ALLOWED_PREFIXES = ("docs/", "tests/")
ALLOWED_FILES = (".github/workflows/engineering-autonomy-v1.yml",)


def evaluate_candidate(
    *,
    metadata: dict[str, Any],
    changed_files: Iterable[str],
) -> dict[str, Any]:
    """Return a deterministic, fail-closed merge decision."""

    files = sorted({str(path) for path in changed_files if str(path)})
    reasons: list[str] = []
    if metadata.get("head_repo") != metadata.get("base_repo"):
        reasons.append("HEAD_REPOSITORY_MISMATCH")
    if metadata.get("draft"):
        reasons.append("DRAFT_PR")
    if MARKER not in str(metadata.get("body") or ""):
        reasons.append("MISSING_LOW_RISK_MARKER")
    if not files:
        reasons.append("NO_CHANGED_FILES")

    disallowed = [
        path
        for path in files
        if path not in ALLOWED_FILES
        and not path.startswith(ALLOWED_PREFIXES)
    ]
    if disallowed:
        reasons.append("DISALLOWED_PATHS")

    eligible = not reasons
    return {
        "eligible": eligible,
        "decision": "AUTO_MERGE" if eligible else "OBSERVE_ONLY",
        "reasons": reasons,
        "changed_files": files,
        "head_sha": metadata.get("head_sha") or "UNKNOWN",
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--changed-files", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    changed_files = args.changed_files.read_text(encoding="utf-8").splitlines()
    print(json.dumps(evaluate_candidate(metadata=metadata, changed_files=changed_files)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

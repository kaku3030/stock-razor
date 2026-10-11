"""Offline, read-only preflight for safely making STOCK RAZOR private.

NEVER prints URL contents or any credential; emits only relative path, line
number, and a controlled public-source dependency category. This is not a
migration or an AWS deployment tool.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

DEPENDENCY_PATTERNS = {
    "PUBLIC_RAW_GITHUB": re.compile(
        r"https?://raw[.]githubusercontent[.]com/kaku3030/stock-razor", re.I
    ),
    "UNAUTHENTICATED_GITHUB_CLONE": re.compile(
        r"https?://github[.]com/kaku3030/stock-razor[.]git", re.I
    ),
}


@dataclass(frozen=True)
class PublicRepoDependency:
    file: str
    line: int
    kind: str


def scan_private_repo_blockers(repo_root: Path) -> list[PublicRepoDependency]:
    """Static scan only; never fetches secrets or accesses GitHub/AWS."""
    root = repo_root.resolve()
    if not root.is_dir():
        raise ValueError("repository root does not exist")
    hits: list[PublicRepoDependency] = []
    for folder in (".github/workflows", "ops/aws"):
        target = root / folder
        if not target.is_dir():
            continue
        for path in sorted(target.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            if path.suffix not in {".yml", ".yaml", ".sh"}:
                continue
            # The report contains only a relative file name and a controlled
            # enum, never a line of source text or credentials.
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for kind, pattern in DEPENDENCY_PATTERNS.items():
                    if pattern.search(line):
                        hits.append(PublicRepoDependency(
                            file=str(path.relative_to(root)), line=index, kind=kind
                        ))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--enforce", action="store_true",
        help="Return nonzero while public-only cloud deployment dependencies remain",
    )
    args = parser.parse_args()
    blockers = scan_private_repo_blockers(args.repo)
    print(json.dumps({
        "repository_visibility_change_authorized": False,
        "private_migration_ready": not bool(blockers),
        "public_fetch_dependency_count": len(blockers),
        "blockers": [asdict(entry) for entry in blockers],
        "aws_changes_performed": False,
        "trading_gates_unchanged": True,
    }, sort_keys=True))
    return 2 if blockers and args.enforce else 0


if __name__ == "__main__":
    raise SystemExit(main())

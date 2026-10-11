"""Offline, read-only preflight for safely making STOCK RAZOR private.

NEVER prints URL contents or any credential; emits only relative path, line
number, and a controlled public-source dependency category.

The static scan is NECESSARY but NOT SUFFICIENT for making the repo private:
a zero-blocker result is not proof of authenticated delivery, IAM scoping,
rollback, recovery, or explicit user approval. This is not a migration or
an AWS deployment tool.
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


def build_static_private_migration_report(
    blockers: list[PublicRepoDependency],
) -> dict[str, object]:
    """Never turn a local grep result into permission to change repo visibility.

    Separate authenticated, externally verified deployment + rollback evidence
    and the user's explicit visibility approval are mandatory. This offline
    script has no way to verify those facts and therefore MUST report them
    unverified regardless of how many grep hits remain.
    """
    return {
        "repository_visibility_change_authorized": False,
        "private_migration_ready": False,
        "static_public_source_dependencies_cleared": not bool(blockers),
        "authenticated_source_delivery_verified": False,
        "aws_restart_recovery_rollback_verified": False,
        "user_visibility_approval_verified": False,
        "public_fetch_dependency_count": len(blockers),
        "blockers": [asdict(entry) for entry in blockers],
        "aws_changes_performed": False,
        "trading_gates_unchanged": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--enforce", action="store_true",
        help="Return nonzero while STATIC public-only dependencies remain; does not authorize PRIVATE",
    )
    args = parser.parse_args()
    blockers = scan_private_repo_blockers(args.repo)
    print(json.dumps(build_static_private_migration_report(blockers), sort_keys=True))
    return 2 if blockers and args.enforce else 0


if __name__ == "__main__":
    raise SystemExit(main())

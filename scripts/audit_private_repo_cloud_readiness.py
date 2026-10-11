#!/usr/bin/env python3
"""Offline, privacy-safe audit of STOCK RAZOR's current private-repo blockers.

Audits only the known US AWS LiveFeed deployment path. It never accesses
GitHub APIs, AWS, broker SDKs, accounts, tokens, filesystem secrets or markets.
An absent known blocker is UNKNOWN, *not* private-migration authorization.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path


WORKFLOW = ".github/workflows/deploy-us-opend-livefeed.yml"
INSTALLER = "ops/aws/install_us_opend_livefeed.sh"
KNOWN_BLOCKERS = (
    (
        "GH_RUNNER_PUBLIC_ORIGIN_LOOKUP",
        WORKFLOW,
        "git ls-remote origin refs/heads/main",
    ),
    (
        "EC2_ANONYMOUS_RAW_INSTALLER",
        WORKFLOW,
        "raw.githubusercontent.com/kaku3030/stock-razor/$REPO_REF/ops/aws/install_us_opend_livefeed.sh",
    ),
    (
        "EC2_ANONYMOUS_RAW_VERIFIER",
        WORKFLOW,
        "raw.githubusercontent.com/kaku3030/stock-razor/$REPO_REF/ops/aws/verify_us_opend_livefeed.sh",
    ),
    (
        "EC2_ANONYMOUS_REPO_CLONE",
        INSTALLER,
        "git clone --filter=blob:none",
    ),
    (
        "EC2_ANONYMOUS_REPO_FETCH",
        INSTALLER,
        'git -C "$INSTALL_ROOT/repo" fetch --depth=1 origin "$REPO_REF"',
    ),
)
VISIBILITY_ABORT_MARKER = "PRIVATE_REPO_CLOUD_SOURCE_TRANSPORT_NOT_MIGRATED"


@dataclass(frozen=True)
class PrivateMigrationReview:
    status: str
    reason: str
    known_blockers: tuple[str, ...] = ()
    missing_files: tuple[str, ...] = ()
    deployment_private_guard_present: bool = False
    audited_workflow_count: int = 1
    scope: str = "US_OPEND_DEPLOY_PATH_ONLY"
    aws_mutations: int = 0
    network_requests: int = 0
    repo_visibility_mutations: int = 0
    radar_admission: str = "BLOCKED"
    source_arbiter_admission: str = "BLOCKED"
    paper_auto_ready: bool = False
    live_trade: bool = False

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "known_blockers": list(self.known_blockers),
            "missing_files": list(self.missing_files),
            "deployment_private_guard_present": self.deployment_private_guard_present,
            "audited_workflow_count": self.audited_workflow_count,
            "scope": self.scope,
            "aws_mutations": self.aws_mutations,
            "network_requests": self.network_requests,
            "repo_visibility_mutations": self.repo_visibility_mutations,
            "radar_admission": self.radar_admission,
            "source_arbiter_admission": self.source_arbiter_admission,
            "paper_auto_ready": self.paper_auto_ready,
            "live_trade": self.live_trade,
        }


def review_private_repo_migration(repo_root: str | Path) -> PrivateMigrationReview:
    """Fail closed; a static code audit cannot prove private-host deployability."""
    try:
        root = Path(repo_root).resolve(strict=True)
    except (OSError, ValueError, RuntimeError):
        return PrivateMigrationReview("UNKNOWN", "REPO_UNAVAILABLE")
    files = {}
    missing = []
    for name in (WORKFLOW, INSTALLER):
        path = root / name
        try:
            if path.is_symlink() or not path.is_file():
                raise OSError("not an ordinary file")
            if path.stat().st_size > 150_000:
                raise OSError("source too large")
            files[name] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError):
            missing.append(name)
    if missing:
        return PrivateMigrationReview(
            "UNKNOWN", "REQUIRED_SOURCE_UNAVAILABLE", missing_files=tuple(missing)
        )
    reasons = tuple(
        code for code, file_name, pattern in KNOWN_BLOCKERS
        if pattern in files[file_name]
    )
    workflow = files[WORKFLOW]
    guarded = (
        VISIBILITY_ABORT_MARKER in workflow
        and 'github.event.repository.private' in workflow
        and 'exit 3' in workflow
    )
    if not guarded:
        return PrivateMigrationReview(
            "BLOCKED", "PRIVATE_REPOSITORY_FAIL_CLOSED_GUARD_MISSING",
            reasons, deployment_private_guard_present=False
        )
    if reasons:
        return PrivateMigrationReview(
            "BLOCKED", "KNOWN_UNAUTHENTICATED_CLOUD_SOURCE_DEPENDENCIES",
            reasons, deployment_private_guard_present=True
        )
    return PrivateMigrationReview(
        "UNKNOWN", "NO_KNOWN_BLOCKERS_BUT_PRIVATE_E2E_NOT_VERIFIED",
        deployment_private_guard_present=True
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline guard for private-repo AWS migration readiness"
    )
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    review = review_private_repo_migration(args.repo_root)
    print(json.dumps(review.to_dict(), sort_keys=True))
    # Useful for CI research, never a positive private-migration permit.
    return 0 if review.status == "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())

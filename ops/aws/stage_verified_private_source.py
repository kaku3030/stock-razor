"""Stage an already authenticated GitHub source tar as an INACTIVE release.

Offline only. No GitHub/AWS download, extraction permission escalation, service
restart, active-path swap, credential handling, or trading admission. The
supplied archive digest MUST be checked against an independent trusted source;
the JSON receipt packaged beside the tar is not a trust root.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

from src.services.private_source_artifact import (
    MAX_ARCHIVE_BYTES,
    PrivateSourceArtifactBlocked,
    verify_private_source_tar,
)

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED = (
    "src/services/private_source_artifact.py",
    "realtime_monitor/readonly_mcp_server.py",
    "ops/aws/install_readonly_mcp.sh",
)


def stage_verified_private_source(
    archive_path: Path,
    *,
    release_root: Path,
    expected_source_commit: str,
    independently_trusted_sha256: str,
) -> dict[str, object]:
    """Stage to <release_root>/<commit>, never activate or replace an old release.

    The commit is an operator pin, not a cryptographic proof of tar origin.
    Trust binding (CI run identity -> commit -> digest) is the responsibility of
    an authenticated delivery process that is not yet implemented here.
    """
    if not isinstance(expected_source_commit, str) or not _SHA40.fullmatch(expected_source_commit):
        raise PrivateSourceArtifactBlocked("exact 40-digit lowercase commit SHA required")
    if release_root.is_symlink() or not release_root.is_dir():
        raise PrivateSourceArtifactBlocked("release root must be an existing non-symlink directory")
    destination = release_root / expected_source_commit
    if destination.exists() or destination.is_symlink():
        raise PrivateSourceArtifactBlocked("release already exists; no replacement permitted")
    if archive_path.is_symlink() or not archive_path.is_file():
        raise PrivateSourceArtifactBlocked("source archive missing or symlinked")
    if archive_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise PrivateSourceArtifactBlocked("source archive exceeds verification byte limit")

    # Fail closed before creating any temporary release directory.
    raw = archive_path.read_bytes()
    verified = verify_private_source_tar(raw, trusted_sha256=independently_trusted_sha256)

    stage = Path(tempfile.mkdtemp(prefix=".unactivated-", dir=release_root))
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            paths = {m.name.rstrip("/") for m in archive.getmembers() if m.isfile()}
            if not set(_REQUIRED).issubset(paths):
                raise PrivateSourceArtifactBlocked("source archive is missing required runtime files")
            for member in archive.getmembers():
                # The shared verifier has already rejected path traversal,
                # links, special entries, duplicates and oversized payloads.
                target = stage.joinpath(*member.name.rstrip("/").split("/"))
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(0o700)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    handle = archive.extractfile(member)
                    if handle is None:
                        raise PrivateSourceArtifactBlocked("source member has no readable content")
                    with handle, target.open("xb") as output:
                        shutil.copyfileobj(handle, output)
                    target.chmod(0o700 if member.mode & 0o111 else 0o600)
        # Do not create any active service pointer or restart a running process.
        # A separate operator must later validate import, health and rollback.
        stage.rename(destination)
    finally:
        if stage.exists():
            shutil.rmtree(stage)

    return {
        "schema": "stock_razor_inactive_stage_v0_1",
        "source_commit_pin": expected_source_commit,
        "verified_source_sha256": verified.archive_sha256,
        "regular_file_count": verified.file_count,
        "stage_path": str(destination),
        "authenticated_delivery_verified_here": False,
        "aws_deployment_performed": False,
        "service_activation_performed": False,
        "paper_auto_ready": False,
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--independently-trusted-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(stage_verified_private_source(
        args.archive, release_root=args.release_root,
        expected_source_commit=args.expected_source_commit,
        independently_trusted_sha256=args.independently_trusted_sha256,
    ), sort_keys=True))


if __name__ == "__main__":
    main()

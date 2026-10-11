#!/usr/bin/env python3
"""Offline immutable source bundle candidate for a future private AWS transport.

No AWS, S3, GitHub API, network, broker SDK or subscription/trading actions.
The caller MUST pass a trusted expected archive SHA at the receiver: a
self-reported manifest by itself is not authenticity or source provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
SCHEMA = "stock_razor_immutable_git_source_tar_v0_1"
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ENTRIES = 30000
MANIFEST_FIELDS = frozenset(
    {"schema", "source_sha", "archive_sha256", "archive_bytes", "entries", "files"}
)
FORBIDDEN_NAMES = frozenset({
    ".env", ".ssh", ".aws", "id_rsa", "id_ed25519",
    "credentials", "credentials.json", "secrets.json",
})


class BundleError(ValueError):
    """A public-safe reason code, never a raw source file or secret value."""


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        raise BundleError("ARCHIVE_UNREADABLE") from None
    return digest.hexdigest()


def _safe_member_name(value: str) -> bool:
    if not isinstance(value, str) or not value or len(value) > 240:
        return False
    if "\\" in value or value.startswith("/") or "\x00" in value:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    chunks = PurePosixPath(value).parts
    if not chunks or any(c in ("", ".", "..") for c in value.split("/")):
        # The final separator on a directory record is allowed.
        if not (value.endswith("/") and all(
            c not in ("", ".", "..") for c in value[:-1].split("/")
        )):
            return False
    if any(c.lower() in FORBIDDEN_NAMES for c in chunks):
        return False
    if any(c.lower().endswith((".pem", ".p12", ".pfx", ".key")) for c in chunks):
        return False
    return True


def _review_archive(path: Path) -> tuple[int, int, int]:
    try:
        archive_bytes = path.stat().st_size
    except OSError:
        raise BundleError("ARCHIVE_UNREADABLE") from None
    if archive_bytes <= 0 or archive_bytes > MAX_ARCHIVE_BYTES:
        raise BundleError("ARCHIVE_SIZE_OUT_OF_BOUNDS")

    count = 0
    files = 0
    seen = set()
    try:
        with tarfile.open(path, mode="r:") as archive:
            for info in archive:
                count += 1
                if count > MAX_ENTRIES:
                    raise BundleError("ARCHIVE_ENTRY_LIMIT")
                if not _safe_member_name(info.name):
                    raise BundleError("ARCHIVE_UNSAFE_SOURCE_PATH")
                if not (info.isfile() or info.isdir()):
                    raise BundleError("ARCHIVE_NONREGULAR_MEMBER")
                if info.size < 0 or info.size > MAX_MEMBER_BYTES:
                    raise BundleError("ARCHIVE_MEMBER_SIZE_LIMIT")
                normalized = info.name.rstrip("/")
                if normalized in seen:
                    raise BundleError("ARCHIVE_DUPLICATE_SOURCE_PATH")
                seen.add(normalized)
                if info.isfile():
                    files += 1
    except BundleError:
        raise
    except (tarfile.TarError, OSError, ValueError, OverflowError):
        raise BundleError("ARCHIVE_PARSE_FAILED") from None
    if not count or not files:
        raise BundleError("ARCHIVE_NO_SOURCE_FILES")
    return archive_bytes, count, files


def _strict_json(pairs):
    out = {}
    for key, val in pairs:
        if key in out:
            raise BundleError("MANIFEST_DUPLICATE_FIELD")
        out[key] = val
    return out


def _load_manifest(path: Path) -> dict:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2048:
            raise BundleError("MANIFEST_UNAVAILABLE")
        with path.open("rb") as stream:
            data = json.load(stream, object_pairs_hook=_strict_json)
    except BundleError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError):
        raise BundleError("MANIFEST_INVALID") from None
    if not isinstance(data, dict) or data.keys() != MANIFEST_FIELDS:
        raise BundleError("MANIFEST_SCHEMA_INVALID")
    return data


def _verify(
    archive: Path, manifest: Path, expected_source_sha: str,
    expected_archive_sha256: str,
) -> dict:
    if not isinstance(expected_source_sha, str) or not SHA40.fullmatch(
        expected_source_sha
    ):
        raise BundleError("EXPECTED_SOURCE_SHA_INVALID")
    if not isinstance(expected_archive_sha256, str) or not SHA64.fullmatch(
        expected_archive_sha256
    ):
        raise BundleError("TRUSTED_ARCHIVE_HASH_REQUIRED")
    if archive.is_symlink() or not archive.is_file():
        raise BundleError("ARCHIVE_UNAVAILABLE")
    record = _load_manifest(manifest)
    if record["schema"] != SCHEMA:
        raise BundleError("MANIFEST_SCHEMA_INVALID")
    if record["source_sha"] != expected_source_sha:
        raise BundleError("SOURCE_REVISION_MISMATCH")
    if record["archive_sha256"] != expected_archive_sha256:
        raise BundleError("MANIFEST_ARCHIVE_HASH_MISMATCH")
    size, entries, files = _review_archive(archive)
    if (
        type(record["archive_bytes"]) is not int
        or type(record["entries"]) is not int
        or type(record["files"]) is not int
        or record["archive_bytes"] != size
        or record["entries"] != entries
        or record["files"] != files
    ):
        raise BundleError("MANIFEST_COUNTS_MISMATCH")
    actual_sha = _hash_file(archive)
    if not hmac.compare_digest(actual_sha, expected_archive_sha256):
        raise BundleError("ARCHIVE_SHA256_MISMATCH")
    return {
        "status": "VERIFIED_OFFLINE_ONLY",
        "reason": "HASH_AND_TAR_STRUCTURE_ONLY_NO_CLOUD_PROVENANCE",
        "source_sha": expected_source_sha,
        "archive_sha256": actual_sha,
        "archive_bytes": size,
        "entries": entries,
        "files": files,
    }


def build_bundle(
    repo_root: str | Path, expected_source_sha: str,
    archive_path: str | Path, manifest_path: str | Path,
) -> dict:
    """Create a Git-commit-pinned archive without reading working-tree files."""
    if not isinstance(expected_source_sha, str) or not SHA40.fullmatch(
        expected_source_sha
    ):
        raise BundleError("EXPECTED_SOURCE_SHA_INVALID")
    root = Path(repo_root).resolve(strict=True)
    archive = Path(archive_path).absolute()
    manifest = Path(manifest_path).absolute()
    if (
        archive == manifest
        or root == archive or root == manifest
        or root in archive.parents or root in manifest.parents
        or archive.exists() or archive.is_symlink()
        or manifest.exists() or manifest.is_symlink()
        or not archive.parent.is_dir() or not manifest.parent.is_dir()
    ):
        raise BundleError("OUTPUT_PATH_UNSAFE")
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise BundleError("LOCAL_GIT_NOT_AVAILABLE") from None
    if head.returncode or head.stdout.strip() != expected_source_sha:
        raise BundleError("CHECKOUT_SHA_MISMATCH")

    temp_archive = None
    temp_manifest = None
    installed = False
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".stock-razor-bundle-", suffix=".tar",
            dir=archive.parent, delete=False,
        ) as tmp:
            temp_archive = Path(tmp.name)
        command = subprocess.run(
            [
                "git", "-C", str(root), "archive", "--format=tar",
                "--output", str(temp_archive), expected_source_sha,
            ],
            capture_output=True, timeout=90, check=False,
        )
        if command.returncode:
            raise BundleError("GIT_ARCHIVE_FAILED")
        size, entries, files = _review_archive(temp_archive)
        digest = _hash_file(temp_archive)
        record = {
            "schema": SCHEMA, "source_sha": expected_source_sha,
            "archive_sha256": digest, "archive_bytes": size,
            "entries": entries, "files": files,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=".stock-razor-manifest-",
            suffix=".json", dir=manifest.parent, delete=False,
        ) as tmp:
            temp_manifest = Path(tmp.name)
            json.dump(record, tmp, sort_keys=True)
            tmp.write("\n")
        # Atomic create-only hard links avoid overwriting an existing output.
        os.link(temp_archive, archive, follow_symlinks=False)
        installed = True
        os.link(temp_manifest, manifest, follow_symlinks=False)
        return {
            "status": "BUILT_OFFLINE_ONLY",
            "reason": "ARCHIVE_REQUIRES_TRUSTED_HASH_AND_PRIVATE_TRANSPORT",
            "source_sha": expected_source_sha,
            "archive_sha256": digest,
            "archive_bytes": size, "entries": entries, "files": files,
        }
    except BundleError:
        raise
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise BundleError("BUNDLE_BUILD_FAILED") from None
    finally:
        if installed and not manifest.is_file():
            archive.unlink(missing_ok=True)
        for transient in (temp_archive, temp_manifest):
            if transient is not None:
                transient.unlink(missing_ok=True)


def verify_bundle(
    archive_path: str | Path, manifest_path: str | Path,
    expected_source_sha: str, expected_archive_sha256: str,
) -> dict:
    return _verify(
        Path(archive_path), Path(manifest_path),
        expected_source_sha, expected_archive_sha256,
    )


def _result(result=None, *, reason=None) -> dict:
    safe = {
        "network_requests": 0, "aws_actions": 0, "provider_calls": 0,
        "repo_visibility_mutations": 0, "subscription_changes": 0,
        "orders_sent": 0, "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED", "paper_auto_ready": False,
        "live_trade": False,
    }
    if reason is not None:
        return {"status": "BLOCKED", "reason": reason, **safe}
    return {**result, **safe}


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Git source tar/hash review")
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build")
    build.add_argument("--repo-root", required=True)
    build.add_argument("--expected-source-sha", required=True)
    build.add_argument("--archive", required=True)
    build.add_argument("--manifest", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--archive", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--expected-source-sha", required=True)
    verify.add_argument("--expected-archive-sha256", required=True)
    args = parser.parse_args()
    try:
        if args.action == "build":
            result = build_bundle(
                args.repo_root, args.expected_source_sha, args.archive, args.manifest
            )
        else:
            result = verify_bundle(
                args.archive, args.manifest, args.expected_source_sha,
                args.expected_archive_sha256,
            )
        output = _result(result)
    except BundleError as exc:
        output = _result(reason=str(exc))
    print(json.dumps(output, sort_keys=True))
    return 0 if output["status"] in (
        "BUILT_OFFLINE_ONLY", "VERIFIED_OFFLINE_ONLY"
    ) else 2


if __name__ == "__main__":
    raise SystemExit(main())

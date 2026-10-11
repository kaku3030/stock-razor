"""Offline verifier for immutable private GitHub-to-cloud source bundles.

This is a *verification primitive*, not an AWS downloader or deployment
or installer. The caller must obtain the expected SHA-256 from an
independent trusted workflow. An archive's self-declared hash is not trust.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import io
from pathlib import PurePosixPath
import re
import tarfile

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 100000
HEX256 = re.compile(r"^[a-f0-9]{64}$")


class PrivateSourceArtifactBlocked(ValueError):
    """An immutable source bundle failed an integrity or path safety gate."""


@dataclass(frozen=True)
class PrivateSourceArtifactReceipt:
    archive_sha256: str
    file_count: int
    total_uncompressed_bytes: int
    verified: bool = True
    extraction_allowed: bool = False
    aws_deployment_performed: bool = False
    paper_auto_ready: bool = False
    live_trade: bool = False


def verify_private_source_tar(
    raw: bytes,
    *,
    trusted_sha256: str,
) -> PrivateSourceArtifactReceipt:
    """Validate bounded tar bytes, reject traversal/links/duplicates, never extract.

    The trusted hash must come from a separately authenticated CI->cloud
    manifest channel, never from the archive being verified.
    """
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_ARCHIVE_BYTES:
        raise PrivateSourceArtifactBlocked("archive is missing or exceeds byte limit")
    if not isinstance(trusted_sha256, str) or not HEX256.fullmatch(trusted_sha256):
        raise PrivateSourceArtifactBlocked("trusted SHA-256 digest is invalid")
    digest = sha256(raw).hexdigest()
    if not hmac.compare_digest(digest, trusted_sha256):
        raise PrivateSourceArtifactBlocked("archive SHA-256 mismatch")
    seen: set[str] = set()
    file_count = 0
    total_bytes = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            members = archive.getmembers()
            if not members or len(members) > MAX_ENTRIES:
                raise PrivateSourceArtifactBlocked("archive member count invalid")
            for member in members:
                path = member.name
                parts = path.rstrip("/").split("/")
                normalized = PurePosixPath(path)
                if (
                    not path
                    or path.startswith("/")
                    or "\\" in path
                    or ":" in path
                    or any(part in ("", ".", "..") for part in parts)
                    or normalized.is_absolute()
                ):
                    raise PrivateSourceArtifactBlocked("unsafe archive member path")
                # No symlink, hardlink, device, FIFO, GNU/PAX extensions,
                # or entry hidden by duplicate names.
                name = str(normalized)
                if name in seen or not (member.isfile() or member.isdir()):
                    raise PrivateSourceArtifactBlocked("archive contains duplicate or unsafe entry")
                seen.add(name)
                if member.isfile():
                    if member.size < 0:
                        raise PrivateSourceArtifactBlocked("negative file size")
                    total_bytes += member.size
                    file_count += 1
                    if total_bytes > MAX_UNCOMPRESSED_BYTES:
                        raise PrivateSourceArtifactBlocked("archive expands beyond size limit")
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise PrivateSourceArtifactBlocked("archive structure is invalid") from exc
    if file_count == 0:
        raise PrivateSourceArtifactBlocked("archive has no regular files")
    return PrivateSourceArtifactReceipt(
        archive_sha256=digest,
        file_count=file_count,
        total_uncompressed_bytes=total_bytes,
    )

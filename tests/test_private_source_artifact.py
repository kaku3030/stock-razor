"""Adversarial offline private-repository source archive checks."""

from hashlib import sha256
import io
import tarfile

import pytest

from src.services.private_source_artifact import (
    PrivateSourceArtifactBlocked,
    verify_private_source_tar,
)


def _tar(entries):
    buff = io.BytesIO()
    with tarfile.open(fileobj=buff, mode="w") as output:
        for path, kind, content in entries:
            info = tarfile.TarInfo(path)
            if kind == "file":
                info.size = len(content)
                output.addfile(info, io.BytesIO(content))
            elif kind == "dir":
                info.type = tarfile.DIRTYPE
                output.addfile(info)
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "../../etc/passwd"
                output.addfile(info)
            elif kind == "hardlink":
                info.type = tarfile.LNKTYPE
                info.linkname = "../../etc/passwd"
                output.addfile(info)
    return buff.getvalue()


def _verify(data):
    return verify_private_source_tar(data, trusted_sha256=sha256(data).hexdigest())


def test_valid_sha_pinned_source_tar_is_read_only():
    content = _tar([
        ("src", "dir", b""),
        ("src/main.py", "file", b"print(1)\n"),
        ("README.md", "file", b"safe\n"),
    ])
    result = _verify(content)
    assert result.verified is True
    assert result.file_count == 2
    assert result.total_uncompressed_bytes == len(b"print(1)\n") + len(b"safe\n")
    assert result.extraction_allowed is False
    assert result.aws_deployment_performed is False
    assert result.paper_auto_ready is False
    assert result.live_trade is False


@pytest.mark.parametrize("member", [
    "../../etc/passwd", "/tmp/config", "src/../evil", "src//evil",
    "src/./evil", "C:/ProgramData/evil", "src\\evil",
])
def test_archive_traversal_and_noncanonical_names_are_blocked(member):
    payload = _tar([(member, "file", b"bad")])
    with pytest.raises(PrivateSourceArtifactBlocked, match="unsafe"):
        _verify(payload)


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_links_blocked_even_when_named_with_safe_path(kind):
    payload = _tar([("safe-link", kind, b"")])
    with pytest.raises(PrivateSourceArtifactBlocked, match="unsafe"):
        _verify(payload)


def test_duplicate_paths_and_missing_files_are_blocked():
    payload = _tar([
        ("same.txt", "file", b"one"), ("same.txt", "file", b"two"),
    ])
    with pytest.raises(PrivateSourceArtifactBlocked, match="duplicate"):
        _verify(payload)
    with pytest.raises(PrivateSourceArtifactBlocked, match="no regular files"):
        _verify(_tar([("empty", "dir", b"")]))


def test_archive_integrity_and_trusted_manifest_required():
    payload = _tar([("code.py", "file", b"ok")])
    with pytest.raises(PrivateSourceArtifactBlocked, match="SHA-256 mismatch"):
        verify_private_source_tar(payload, trusted_sha256="0" * 64)
    with pytest.raises(PrivateSourceArtifactBlocked, match="digest"):
        verify_private_source_tar(payload, trusted_sha256="UNKNOWN")
    with pytest.raises(PrivateSourceArtifactBlocked, match="missing"):
        verify_private_source_tar(b"", trusted_sha256="0" * 64)

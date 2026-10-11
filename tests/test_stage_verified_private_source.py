"""No-network proof that staged GitHub source never mutates running services."""

from hashlib import sha256
import io
import tarfile

import pytest

from ops.aws.stage_verified_private_source import stage_verified_private_source
from src.services.private_source_artifact import PrivateSourceArtifactBlocked

COMMIT = "a" * 40
REQUIRED = (
    "src/services/private_source_artifact.py",
    "realtime_monitor/readonly_mcp_server.py",
    "ops/aws/install_readonly_mcp.sh",
)


def _tar(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for name, data in entries:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return output.getvalue()


def _stage(tmp_path, raw, *, digest=None, sha=COMMIT):
    source = tmp_path / "source.tar"
    source.write_bytes(raw)
    releases = tmp_path / "releases"
    releases.mkdir(exist_ok=True)
    return stage_verified_private_source(
        source, release_root=releases,
        expected_source_commit=sha,
        independently_trusted_sha256=digest or sha256(raw).hexdigest(),
    )


def test_stages_pinned_source_without_activation_or_trading(tmp_path):
    raw = _tar([(name, b"trusted source") for name in REQUIRED])
    receipt = _stage(tmp_path, raw)
    release = tmp_path / "releases" / COMMIT
    assert receipt["verified_source_sha256"] == sha256(raw).hexdigest()
    assert receipt["source_commit_pin"] == COMMIT
    assert (release / REQUIRED[0]).read_bytes() == b"trusted source"
    assert receipt["service_activation_performed"] is False
    assert receipt["aws_deployment_performed"] is False
    assert receipt["paper_auto_ready"] is False
    assert receipt["radar_admission"] == "BLOCKED"
    assert receipt["source_arbiter_admission"] == "BLOCKED"
    assert receipt["live_trade"] is False
    assert not (tmp_path / "releases" / "current").exists()
    with pytest.raises(PrivateSourceArtifactBlocked, match="already exists"):
        _stage(tmp_path, raw)


def test_untrusted_digest_leaves_no_release(tmp_path):
    raw = _tar([(name, b"trusted") for name in REQUIRED])
    with pytest.raises(PrivateSourceArtifactBlocked, match="mismatch"):
        _stage(tmp_path, raw, digest="0" * 64)
    assert not list((tmp_path / "releases").iterdir())


def test_missing_required_runtime_path_cleans_stage(tmp_path):
    raw = _tar([(REQUIRED[0], b"incomplete")])
    with pytest.raises(PrivateSourceArtifactBlocked, match="missing required runtime"):
        _stage(tmp_path, raw)
    assert not list((tmp_path / "releases").iterdir())


def test_reject_symlink_release_root_and_archive(tmp_path):
    raw = _tar([(name, b"source") for name in REQUIRED])
    releases = tmp_path / "releases"
    releases.mkdir()
    archive = tmp_path / "real.tar"
    archive.write_bytes(raw)
    (tmp_path / "release-link").symlink_to(releases, target_is_directory=True)
    with pytest.raises(PrivateSourceArtifactBlocked, match="non-symlink"):
        stage_verified_private_source(
            archive, release_root=tmp_path / "release-link",
            expected_source_commit=COMMIT,
            independently_trusted_sha256=sha256(raw).hexdigest(),
        )
    (tmp_path / "source-link").symlink_to(archive)
    with pytest.raises(PrivateSourceArtifactBlocked, match="symlinked"):
        stage_verified_private_source(
            tmp_path / "source-link", release_root=releases,
            expected_source_commit=COMMIT,
            independently_trusted_sha256=sha256(raw).hexdigest(),
        )


def test_invalid_commit_pin_rejected(tmp_path):
    raw = _tar([(name, b"code") for name in REQUIRED])
    with pytest.raises(PrivateSourceArtifactBlocked, match="40-digit"):
        _stage(tmp_path, raw, sha="main")

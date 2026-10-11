"""Synthetic git snapshots only: no GitHub token, AWS, cloud or provider I/O."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import pytest

from ops.aws.private_source_bundle import (
    BundleError,
    MAX_ARCHIVE_BYTES,
    _review_archive,
    build_bundle,
    main,
    verify_bundle,
)


def _git(root, *args):
    proc = subprocess.run(
        ["git", "-C", str(root), *args], text=True,
        capture_output=True, timeout=10, check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "synthetic-repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "CI synthetic")
    _git(root, "config", "user.email", "ci-synthetic@example.invalid")
    (root / "src").mkdir()
    (root / "src" / "core.py").write_text("VALUE = 'committed-safe'\n")
    (root / "README.md").write_text("synthetic-only\n")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "synthetic fixture")
    return root, _git(root, "rev-parse", "HEAD")


def _build(tmp_path, source):
    repo, sha = source
    archive = tmp_path / "offline-release.tar"
    manifest = tmp_path / "offline-release.json"
    record = build_bundle(repo, sha, archive, manifest)
    return archive, manifest, record


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable needed")
def test_bundle_ignores_dirty_working_tree_and_is_verifiable_with_external_hash(
    source, tmp_path,
):
    root, sha = source
    # A dirty checkout must not leak uncommitted or untracked source changes.
    (root / "src" / "core.py").write_text("VALUE = 'uncommitted-secret'\n")
    (root / "src" / "untracked-secret.txt").write_text("never-distribute\n")
    archive, manifest, built = _build(tmp_path, source)
    assert built["status"] == "BUILT_OFFLINE_ONLY"
    assert built["source_sha"] == sha
    assert built["archive_bytes"] > 0
    assert built["files"] == 2
    assert built["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        assert "src/core.py" in names
        assert "src/untracked-secret.txt" not in names
        contents = tar.extractfile("src/core.py").read().decode()
        assert "committed-safe" in contents
        assert "uncommitted-secret" not in contents
    verified = verify_bundle(archive, manifest, sha, built["archive_sha256"])
    assert verified["status"] == "VERIFIED_OFFLINE_ONLY"
    assert verified["reason"] == "HASH_AND_TAR_STRUCTURE_ONLY_NO_CLOUD_PROVENANCE"
    assert verified["files"] == 2
    assert json.loads(manifest.read_text())["source_sha"] == sha


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable needed")
def test_sha_mismatch_and_existing_target_do_not_overwrite(source, tmp_path):
    root, sha = source
    archive = tmp_path / "release.tar"
    manifest = tmp_path / "release.json"
    with pytest.raises(BundleError, match="CHECKOUT_SHA_MISMATCH"):
        build_bundle(root, "0" * 40, archive, manifest)
    assert not archive.exists() and not manifest.exists()
    archive.write_bytes(b"EXISTING_ARTIFACT")
    with pytest.raises(BundleError, match="OUTPUT_PATH_UNSAFE"):
        build_bundle(root, sha, archive, manifest)
    assert archive.read_bytes() == b"EXISTING_ARTIFACT"


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable needed")
def test_wrong_hash_changed_manifest_and_corrupt_archive_fail_closed(
    source, tmp_path,
):
    archive, manifest, built = _build(tmp_path, source)
    _, sha = source
    with pytest.raises(BundleError, match="TRUSTED_ARCHIVE_HASH_REQUIRED"):
        verify_bundle(archive, manifest, sha, "")
    with pytest.raises(BundleError, match="SOURCE_REVISION_MISMATCH"):
        verify_bundle(archive, manifest, "1" * 40, built["archive_sha256"])
    with pytest.raises(BundleError, match="MANIFEST_ARCHIVE_HASH_MISMATCH"):
        verify_bundle(archive, manifest, sha, "0" * 64)
    tampered = json.loads(manifest.read_text())
    tampered["files"] = tampered["files"] + 1
    manifest.write_text(json.dumps(tampered))
    with pytest.raises(BundleError, match="MANIFEST_COUNTS_MISMATCH"):
        verify_bundle(archive, manifest, sha, built["archive_sha256"])
    manifest.write_text(json.dumps({**tampered, "files": built["files"]}))
    raw = archive.read_bytes()
    assert b"committed-safe" in raw
    archive.write_bytes(raw.replace(b"committed-safe", b"committed-fake"))
    with pytest.raises(BundleError, match="ARCHIVE_SHA256_MISMATCH"):
        verify_bundle(archive, manifest, sha, built["archive_sha256"])


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable needed")
def test_duplicate_manifest_json_keys_and_missing_input_do_not_leak(source, tmp_path):
    archive, manifest, built = _build(tmp_path, source)
    _, sha = source
    existing = manifest.read_text()
    manifest.write_text('{"schema":"SAFE","schema":"LEAK","private_account":"123"}')
    with pytest.raises(BundleError, match="MANIFEST_DUPLICATE_FIELD"):
        verify_bundle(archive, manifest, sha, built["archive_sha256"])
    manifest.write_text(existing)
    with pytest.raises(BundleError, match="ARCHIVE_UNAVAILABLE"):
        verify_bundle(tmp_path / "missing.tar", manifest, sha, built["archive_sha256"])


def test_malicious_tar_traversal_symlink_and_secret_are_never_accepted(tmp_path):
    cases = [("../escape.txt", "file"), ("credentials.json", "file"),
             ("safe.pem", "file"), ("safe/../evil", "file"),
             ("src/untrusted.py", "symlink")]
    for index, (name, kind) in enumerate(cases):
        path = tmp_path / f"bad-{index}.tar"
        with tarfile.open(path, "w") as tar:
            data = b"test"
            info = tarfile.TarInfo(name)
            if kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = "/private/secret"
            else:
                info.size = len(data)
            tar.addfile(info, None if kind == "symlink" else io.BytesIO(data))
        with pytest.raises(BundleError):
            _review_archive(path)


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable needed")
def test_git_symlinks_and_tracked_private_env_block_bundle(source, tmp_path):
    root, _ = source
    (root / ".env").write_text("FAKE_TOKEN=synthetic\n")
    _git(root, "add", ".env")
    _git(root, "commit", "-m", "synthetic private file")
    sha = _git(root, "rev-parse", "HEAD")
    with pytest.raises(BundleError, match="ARCHIVE_UNSAFE_SOURCE_PATH"):
        build_bundle(root, sha, tmp_path / "x.tar", tmp_path / "x.json")
    assert not (tmp_path / "x.tar").exists()
    assert not (tmp_path / "x.json").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable needed")
def test_caller_can_set_stricter_maximum_archive_size(monkeypatch, source, tmp_path):
    import ops.aws.private_source_bundle as module

    monkeypatch.setattr(module, "MAX_ARCHIVE_BYTES", 10)
    with pytest.raises(BundleError, match="ARCHIVE_SIZE_OUT_OF_BOUNDS"):
        build_bundle(
            source[0], source[1],
            tmp_path / "max.tar", tmp_path / "max.json",
        )


@pytest.mark.skipif(shutil.which("git") is None, reason="Git executable needed")
def test_cli_outputs_only_machine_safe_evidence_and_trading_stays_blocked(
    source, tmp_path, monkeypatch, capsys,
):
    root, sha = source
    archive = tmp_path / "ship.tar"
    manifest = tmp_path / "ship.json"
    monkeypatch.setattr(sys, "argv", [
        "private_source_bundle.py", "build",
        "--repo-root", str(root), "--expected-source-sha", sha,
        "--archive", str(archive), "--manifest", str(manifest),
    ])
    assert main() == 0
    out = capsys.readouterr().out
    j = json.loads(out)
    assert j["status"] == "BUILT_OFFLINE_ONLY"
    assert j["network_requests"] == j["aws_actions"] == 0
    assert j["repo_visibility_mutations"] == 0
    assert j["subscription_changes"] == j["orders_sent"] == 0
    assert j["radar_admission"] == "BLOCKED"
    assert j["source_arbiter_admission"] == "BLOCKED"
    assert j["paper_auto_ready"] is False and j["live_trade"] is False
    assert "ci-synthetic@example.invalid" not in out
    monkeypatch.setattr(sys, "argv", [
        "private_source_bundle.py", "verify",
        "--archive", str(archive), "--manifest", str(manifest),
        "--expected-source-sha", sha,
        "--expected-archive-sha256", j["archive_sha256"],
    ])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED_OFFLINE_ONLY"


def test_no_network_or_aws_cli_in_offline_contract():
    script = Path("ops/aws/private_source_bundle.py").read_text(encoding="utf-8")
    assert "subprocess.run(" in script
    assert "subprocess.run(\n            [\n                \"git\"" in script
    assert "import boto3" not in script
    assert "import requests" not in script
    assert "aws ssm" not in script
    assert "aws s3" not in script

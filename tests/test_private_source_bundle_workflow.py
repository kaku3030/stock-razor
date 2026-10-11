"""Manual source bundle must remain an offline build, never an AWS deploy."""

from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/private-source-bundle-manual.yml"
)


def test_private_source_bundle_is_manual_and_has_no_aws_credentials():
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "  workflow_dispatch:" in body
    assert "  push:" not in body
    assert "  schedule:" not in body
    assert "  contents: read" in body
    assert "  id-token: write" not in body
    assert "aws-actions/configure-aws-credentials" not in body
    assert "aws ssm " not in body
    assert "aws ec2 " not in body
    assert "aws s3 " not in body
    assert "${{ secrets." not in body


def test_source_bundle_is_from_pinned_git_commit_and_never_deployed():
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "persist-credentials: false" in body
    assert "EXPECTED_SOURCE_SHA: ${{ github.sha }}" in body
    assert 'actual="$(git rev-parse HEAD)"' in body
    assert 'test "$actual" = "$EXPECTED_SOURCE_SHA"' in body
    assert "git archive --format=tar" in body
    assert "verify_private_source_tar" in body
    assert '"authenticated_cloud_receipt": False' in body
    assert '"cloud_deployment_performed": False' in body
    assert '"private_migration_ready": False' in body


def test_bundle_retention_is_short_and_source_identity_explicit():
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/upload-artifact@v4" in body
    assert "stock-razor-source-${{ github.sha }}" in body
    assert "retention-days: 3" in body
    assert '"source_commit_sha": os.environ["EXPECTED_SOURCE_SHA"]' in body
    assert '"bundle_sha256": receipt.archive_sha256' in body


def test_bundle_excludes_docs_only_media_to_fit_strict_verifier_limit():
    body = WORKFLOW.read_text(encoding="utf-8")
    assert "HEAD ':(exclude)docs/assets' ':(exclude)CLAUDE.md'" in body
    assert 'test "$(wc -c < "$BUNDLE_PATH")" -le 67108864' in body
    assert "SOURCE_BUNDLE_EXCEEDS_VERIFIER_LIMIT" in body
    assert "TRACKED_SOURCE_EXCLUDING_DOCS_ASSETS_AND_CLAUDE_LINK" in body
    assert "source-tree-paths.txt" in body
    assert "SOURCE_BUNDLE_EXCLUDED_PATH_PRESENT" in body
    assert "SOURCE_BUNDLE_RUNTIME_PATH_MISSING" in body
    for required in (
        "src/services/private_source_artifact.py",
        "realtime_monitor/readonly_mcp_server.py",
        "ops/aws/install_readonly_mcp.sh",
    ):
        assert required in body


def test_actual_git_archive_is_bounded_and_verifiable_when_checkout_available():
    """Integration gate on checked-out CI commit, unlike a static YAML check."""
    import hashlib
    import io
    import shutil
    import subprocess
    import tarfile

    import pytest

    from src.services.private_source_artifact import verify_private_source_tar

    root = Path(__file__).resolve().parents[1]
    if not shutil.which("git") or not (root / ".git").exists():
        pytest.skip("requires a real Git checkout")
    output = subprocess.run(
        ["git", "archive", "--format=tar", "HEAD", ":(exclude)docs/assets", ":(exclude)CLAUDE.md"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    assert output, "archive must not be empty"
    assert len(output) <= 64 * 1024 * 1024, "source bundle exceeds verifier limit"
    receipt = verify_private_source_tar(
        output, trusted_sha256=hashlib.sha256(output).hexdigest()
    )
    assert receipt.verified is True
    assert receipt.aws_deployment_performed is False
    assert receipt.extraction_allowed is False
    with tarfile.open(fileobj=io.BytesIO(output), mode="r:") as archive:
        paths = {member.name for member in archive.getmembers()}
    assert not any(path.startswith("docs/assets/") for path in paths)
    assert "CLAUDE.md" not in paths
    assert {
        "src/services/private_source_artifact.py",
        "realtime_monitor/readonly_mcp_server.py",
        "ops/aws/install_readonly_mcp.sh",
    } <= paths


def test_workflow_is_well_formed_and_contains_exactly_one_job_and_steps_section():
    """Guard against accidental YAML concatenation after the upload-artifact step."""
    from pathlib import Path
    import yaml

    source = WORKFLOW.read_text(encoding="utf-8")
    document = yaml.safe_load(source)
    assert document["jobs"]["produce-source-bundle"]["runs-on"] == "ubuntu-latest"
    assert len(document["jobs"]["produce-source-bundle"]["steps"]) == 3
    assert document["jobs"]["produce-source-bundle"]["steps"][-1]["uses"] == "actions/upload-artifact@v4"
    assert source.count("      - name: Upload immutable bundle") == 1
    assert source.count('test "$(wc -c < "$BUNDLE_PATH")"') == 1

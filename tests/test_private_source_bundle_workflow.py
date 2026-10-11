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

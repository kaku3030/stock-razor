"""Regression for sanitizing enhanced AWS IAM AccessDenied reasons.

Synthetic messages only. No AWS credentials, Secrets Manager calls, or raw
policy/ARN/secret values enter any test output.
"""
from pathlib import Path
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops/aws/audit_tickflow_secret_access.sh"
WORKFLOW = ROOT / ".github/workflows/audit-tickflow-secret-access.yml"


def _classifier():
    script = SCRIPT.read_text(encoding="utf-8")
    start = "classify_denial_cause() {"
    end = "\n}\n\naws_cli="
    assert start in script, "Denied Secret reads must have a safe evidence classifier"
    return start + script.split(start, 1)[1].split(end, 1)[0] + "\n}"


@pytest.mark.parametrize(
    ("aws_stderr", "expected"),
    [
        (
            "An error occurred (AccessDeniedException): User is not authorized to perform: secretsmanager:DescribeSecret because no identity-based policy allows the secretsmanager:DescribeSecret action",
            "IDENTITY_NO_ALLOW",
        ),
        (
            "An error occurred (AccessDeniedException): with an explicit deny in an identity-based policy: arn:aws:iam::000000000000:policy/synthetic",
            "IDENTITY_EXPLICIT_DENY",
        ),
        (
            "An error occurred (AccessDeniedException): because no resource-based policy allows the secretsmanager:GetSecretValue action",
            "RESOURCE_NO_ALLOW",
        ),
        (
            "An error occurred (AccessDeniedException): with an explicit deny in a resource-based policy",
            "RESOURCE_EXPLICIT_DENY",
        ),
        (
            "An error occurred (AccessDeniedException): because no service control policy allows the secretsmanager:DescribeSecret action",
            "SCP_NO_ALLOW",
        ),
        (
            "An error occurred (AccessDeniedException): with an explicit deny in a service control policy",
            "SCP_EXPLICIT_DENY",
        ),
        (
            "An error occurred (AccessDeniedException): with an explicit deny in a resource control policy",
            "RCP_EXPLICIT_DENY",
        ),
        (
            "An error occurred (AccessDeniedException): because no permissions boundary allows this action",
            "PERMISSIONS_BOUNDARY",
        ),
        (
            "An error occurred (AccessDeniedException): with an explicit deny in a session policy",
            "SESSION_POLICY",
        ),
        (
            "An error occurred (AccessDeniedException): Redacted policy ARN synthetic and generic denial",
            "UNKNOWN",
        ),
        (
            "An error occurred (EndpointConnectionError): network unreachable",
            "NOT_APPLICABLE",
        ),
    ],
)
def test_denial_classification_is_fixed_vocabulary_without_raw_leaks(
    aws_stderr, expected
):
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "error.log"
        path.write_text(aws_stderr, encoding="utf-8")
        process = subprocess.run(
            ["bash", "-c", _classifier() + '\nclassify_denial_cause "$1"', "--", str(path)],
            capture_output=True,
            text=True,
            check=True,
            timeout=8,
        )
    assert process.stdout.strip() == expected
    assert process.stderr == ""
    assert "000000000000" not in process.stdout
    assert "synthetic" not in process.stdout.lower()


def test_workflow_exposes_only_allowlisted_denial_categories():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    assert workflow.count("DESCRIBE_DENY_CAUSE") == 2
    assert workflow.count("GET_SECRET_DENY_CAUSE") == 2
    assert 'TICKFLOW_SECRET_AUDIT_DESCRIBE_DENY_CAUSE=' in script
    assert 'TICKFLOW_SECRET_AUDIT_GET_SECRET_DENY_CAUSE=' in script
    assert "printf '%s\\n' \"$report\" | grep -Ex" in workflow
    assert "TICKFLOW_SECRET_AUDIT_SECRETSTRING=NOT_EMITTED" in script
    assert "TICKFLOW_SECRET_AUDIT_MUTATIONS=NONE" in script

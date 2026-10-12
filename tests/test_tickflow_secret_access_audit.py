from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/audit-tickflow-secret-access.yml"
SCRIPT = ROOT / "ops/aws/audit_tickflow_secret_access.sh"


def test_secret_access_audit_is_explicit_and_secret_safe():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    assert "type: boolean" not in workflow
    assert "id-token: write" in workflow
    assert "AWS-RunShellScript" in workflow
    assert "SecretString" not in workflow + script
    assert "SecretBinary" not in workflow + script
    assert "TICKFLOW_SECRET_AUDIT_SECRETSTRING=NOT_EMITTED" in script
    assert "TICKFLOW_SECRET_AUDIT_MUTATIONS=NONE" in script
    assert "TICKFLOW_SECRET_AUDIT_FAILED_STAGE" in script
    assert "get-secret-value" in script
    assert "--query VersionId" in script
    assert "get-resource-policy" in script
    assert 'printf "%s\\n" "$policy' not in script


def test_reference_is_restricted_to_approved_name_or_arn():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "stock-razor/tickflow/premium" in script
    assert "arn:aws:secretsmanager:ap-northeast-1:888425712426:secret:stock-razor/tickflow/premium-" in script
    assert "ORGANIZATION_POLICY=NOT_VERIFIED" in script

"""Fail-closed AWS TickFlow isolation, scope, and provenance contract tests."""

from pathlib import Path
import yaml
import pytest

from scripts.probe_tickflow_isolated import build_probe

CLOUD = Path("ops/aws/run_tickflow_cloud_isolated_smoke.sh").read_text(encoding="utf-8")
WORKFLOW = Path(".github/workflows/probe-tickflow-aws-isolated.yml").read_text(encoding="utf-8")


def test_cloud_workflow_dispatch_restricts_modes_and_is_oidc_ssm_only():
    wf = yaml.safe_load(WORKFLOW)
    assert wf["permissions"] == {"id-token": "write", "contents": "read"}
    job = wf["jobs"]["cloud-isolated-probe"]
    assert job["env"]["AWS_REGION"] == "ap-northeast-1"
    assert job["env"]["TARGET_INSTANCE_ID"] == "i-01738342af3efac72"
    assert job["timeout-minutes"] <= 12
    assert "aws-actions/configure-aws-credentials@v4" in WORKFLOW
    assert "AWS-RunShellScript" in WORKFLOW
    assert "ssm send-command" in WORKFLOW
    dispatch = wf.get("on", wf.get(True))["workflow_dispatch"]
    modes = dispatch["inputs"]["mode"]
    assert modes["type"] == "choice"
    assert modes["default"] == "metadata"
    assert modes["options"] == ["metadata", "free"]
    assert '[[ "$PROBE_MODE" == metadata || "$PROBE_MODE" == free ]]' in WORKFLOW


def test_cloud_workflow_uses_pinned_sha256_artifact_delivery():
    assert 'script_sha="$(git rev-parse HEAD)"' in WORKFLOW
    assert "sha256sum ops/aws/run_tickflow_cloud_isolated_smoke.sh" in WORKFLOW
    assert "sha256sum scripts/probe_tickflow_isolated.py" in WORKFLOW
    assert "sha256sum ops/requirements/tickflow-isolated-v0.1.txt" in WORKFLOW
    assert "sha256sum -c -" in WORKFLOW
    assert "sha256sum -c -" in CLOUD
    assert "PROBE_SHA256_MISMATCH" in CLOUD
    assert "REQUIREMENTS_SHA256_MISMATCH" in CLOUD
    assert "CLOUD_TICKFLOW_SOURCE_INTEGRITY" not in CLOUD  # exact key tested below
    assert "TICKFLOW_CLOUD_SOURCE_INTEGRITY=PASS" in CLOUD


def test_runtime_never_installs_into_radar_or_reads_paid_secret():
    assert "/opt/stock-razor-tickflow-isolated" in CLOUD
    assert "unset TICKFLOW_API_KEY" in CLOUD
    assert "PREMIUM_REQUIRES_SEPARATE_ENTITLEMENT_GATE" in CLOUD
    assert "mkdir -p" in CLOUD
    assert "python3 -m venv" in CLOUD
    assert "--max-time 20" in CLOUD
    assert "LIVE_TRADE=NO" in CLOUD
    assert "TICKFLOW_CLOUD_DATA_ADMISSION=BLOCKED" in CLOUD
    assert '"location") == "AWS_TOKYO_SSM_ISOLATE"' in CLOUD
    assert '"source_arbiter_admission") == "BLOCKED"' in CLOUD
    assert '"data_qualification") == "NOT_VERIFIED"' in CLOUD
    for bad in (
        "systemctl restart", "systemctl stop", "pip install --upgrade",
        "OpenUSTradeContext", "submit_order(", "place_order(",
        "aws secretsmanager get-secret-value", "aws ssm get-parameter",
    ):
        assert bad not in WORKFLOW
        assert bad not in CLOUD


def test_location_explicitly_marks_aws_and_never_promotes_entitlement():
    class NoInit:
        @classmethod
        def free(cls):
            raise AssertionError("not supposed to call free")
    probe = build_probe(
        mode="metadata",
        symbols=("159611.SZ",),
        location="AWS_TOKYO_SSM_ISOLATE",
        client_factory=NoInit,
        credential_present=False,
        sdk_version="0.1.25",
    )
    assert probe["location"] == "AWS_TOKYO_SSM_ISOLATE"
    assert probe["api_key_present"] is False
    assert probe["cloud_independence"] == "NOT_VERIFIED"
    assert probe["real_market_slo"] == "NOT_VERIFIED"
    assert probe["data_qualification"] == "NOT_VERIFIED"
    assert probe["radar_admission"] == "BLOCKED"
    assert probe["canonical_write"] is False
    assert probe["live_trade"] is False
    with pytest.raises(ValueError):
        build_probe(
            mode="metadata", symbols=("159611.SZ",),
            location="UNVERIFIED_CUSTOM_LOCATION", client_factory=NoInit
        )

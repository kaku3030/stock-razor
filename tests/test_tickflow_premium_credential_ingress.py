import json

import pytest

from scripts.tickflow_premium_credential import (
    premium_ingress_enabled,
    validate_secret_arn,
    validate_secret_document,
)
from pathlib import Path


PREMIUM_WORKFLOW = Path(".github/workflows/probe-tickflow-aws-premium.yml").read_text(encoding="utf-8")
PREMIUM_BOOTSTRAP = Path("ops/aws/run_tickflow_premium_probe.sh").read_text(encoding="utf-8")


def test_premium_path_is_dormant_and_pins_all_remote_artifacts():
    assert 'default: false' in PREMIUM_WORKFLOW
    assert 'if: ${{ inputs.enable_premium_probe == true' in PREMIUM_WORKFLOW
    assert 'ref: ${{ github.sha }}' in PREMIUM_WORKFLOW
    assert 'bootstrap_hash=' in PREMIUM_WORKFLOW
    assert 'sha256sum -c -' in PREMIUM_BOOTSTRAP
    assert 'unset TICKFLOW_PREMIUM_PROBE_ENABLED TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED' in PREMIUM_BOOTSTRAP
    assert 'RADAR_ADMISSION=BLOCKED' in PREMIUM_BOOTSTRAP
    assert 'LIVE_TRADE=NO' in PREMIUM_BOOTSTRAP
    for forbidden in ('aws iam', 'aws kms', 'aws secretsmanager put', 'aws secretsmanager delete'):
        assert forbidden not in PREMIUM_WORKFLOW.lower()
        assert forbidden not in PREMIUM_BOOTSTRAP.lower()


def test_remote_premium_bootstrap_hash_verification_precedes_execution():
    """The SSM target must authenticate fetched code before first execution."""
    assert "sr-tickflow-premium-bootstrap.XXXXXXXX" in PREMIUM_WORKFLOW
    remote = PREMIUM_WORKFLOW.split("read -r -d '' remote <<REMOTE", 1)[1]
    remote = remote.split("          REMOTE", 1)[0]
    assert "set -euo pipefail" not in remote
    assert "trap 'rc=\\$?; if [ \"\\$rc\" -ne 0 ]" in remote
    assert "TICKFLOW_PREMIUM_BOOTSTRAP_STAGE=%s" in PREMIUM_WORKFLOW
    assert "bootstrap_stage=VERIFY_BOOTSTRAP_HASH" in PREMIUM_WORKFLOW
    assert "/tmp/run_tickflow_premium_probe.sh" not in PREMIUM_WORKFLOW
    assert "sha256sum -c - >/dev/null" in PREMIUM_WORKFLOW
    assert PREMIUM_WORKFLOW.index("sha256sum -c - >/dev/null") < PREMIUM_WORKFLOW.index(r'bash "\$temp_dir/bootstrap.sh"')


def test_premium_failure_diagnostics_keep_cleanup_and_stage_reporting_combined():
    assert PREMIUM_BOOTSTRAP.count("trap cleanup EXIT") == 1
    assert "trap '" not in PREMIUM_BOOTSTRAP
    assert "trap - EXIT" in PREMIUM_BOOTSTRAP
    assert 'unset TICKFLOW_API_KEY secret_json' in PREMIUM_BOOTSTRAP
    assert 'exit "$rc"' in PREMIUM_BOOTSTRAP
    assert "TICKFLOW_PREMIUM_SSM_RESPONSE_CODE=" in PREMIUM_WORKFLOW
    assert "TICKFLOW_PREMIUM_(FAILED_STAGE|BOOTSTRAP_STAGE)=[A-Z_]+" in PREMIUM_WORKFLOW
    assert "StandardErrorContent" in PREMIUM_WORKFLOW
    assert "StatusDetails" in PREMIUM_WORKFLOW
    assert "TICKFLOW_PREMIUM_FAILED_STAGE=SSM_REMOTE_COMMAND" in PREMIUM_WORKFLOW
    assert "TICKFLOW_PREMIUM_FAILED_STAGE=SSM_COMMAND_TIMEOUT" in PREMIUM_WORKFLOW
    assert "response_code=UNKNOWN" in PREMIUM_WORKFLOW


def test_premium_bootstrap_resolves_aws_cli_without_exposing_command_output():
    assert 'command -v aws 2>/dev/null || true' in PREMIUM_BOOTSTRAP
    assert 'for candidate in /usr/local/bin/aws /usr/bin/aws /snap/bin/aws /usr/local/aws-cli/v2/current/bin/aws /opt/aws-cli/v2/current/bin/aws' in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_AWS_CLI=UNAVAILABLE' in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_AWS_CLI_VERSION=' in PREMIUM_BOOTSTRAP
    assert 'secret_json="$("$aws_cli" secretsmanager get-secret-value' in PREMIUM_BOOTSTRAP
    assert '2>&1 || true' in PREMIUM_BOOTSTRAP
    assert 'StandardOutputContent' not in PREMIUM_BOOTSTRAP
    assert 'StandardErrorContent' not in PREMIUM_BOOTSTRAP
    assert 'aws_version_raw=' in PREMIUM_BOOTSTRAP
    assert '|| true)' in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_AWS_CLI=(AVAILABLE|UNAVAILABLE|INVALID)' in PREMIUM_WORKFLOW
    assert 'TICKFLOW_PREMIUM_AWS_CLI_PATH=' in PREMIUM_WORKFLOW
    assert 'TICKFLOW_PREMIUM_AWS_CLI_VERSION=' in PREMIUM_WORKFLOW


def test_ingress_requires_exact_opt_in():
    assert premium_ingress_enabled("true") is True
    assert premium_ingress_enabled("TRUE") is False
    assert premium_ingress_enabled(None) is False


def test_secret_arn_is_narrow_and_region_bound():
    value = "arn:aws:secretsmanager:ap-northeast-1:888425712426:secret:stock-razor/tickflow/premium-main-123456"
    assert validate_secret_arn(value) == value
    for bad in (None, "arn:aws:secretsmanager:us-east-1:888425712426:secret:x", value + "/other"):
        with pytest.raises(ValueError):
            validate_secret_arn(bad)


def test_secret_document_has_only_api_key_and_never_serializes_payload():
    key = validate_secret_document(json.loads('{"api_key":"secret-value"}'))
    assert key == "secret-value"
    with pytest.raises(ValueError):
        validate_secret_document({"api_key": "secret-value", "extra": "x"})

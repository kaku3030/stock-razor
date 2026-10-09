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
    assert "TICKFLOW_PREMIUM_(FAILED_STAGE|BOOTSTRAP_STAGE|AWS_CLI_STAGE)=[A-Z_]+" in PREMIUM_WORKFLOW
    assert "StandardErrorContent" in PREMIUM_WORKFLOW
    assert "StatusDetails" in PREMIUM_WORKFLOW
    assert "TICKFLOW_PREMIUM_FAILED_STAGE=SSM_REMOTE_COMMAND" in PREMIUM_WORKFLOW
    assert "TICKFLOW_PREMIUM_FAILED_STAGE=SSM_COMMAND_TIMEOUT" in PREMIUM_WORKFLOW
    assert "response_code=UNKNOWN" in PREMIUM_WORKFLOW


def test_premium_bootstrap_resolves_aws_cli_without_exposing_command_output():
    assert 'command -v aws 2>/dev/null || true' in PREMIUM_BOOTSTRAP
    assert 'for candidate in "$root/bin/aws" /usr/local/bin/aws /usr/bin/aws /snap/bin/aws /usr/local/aws-cli/v2/current/bin/aws /opt/aws-cli/v2/current/bin/aws' in PREMIUM_BOOTSTRAP
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
    assert 'TICKFLOW_PREMIUM_AWS_CLI_ARCH=(x86_64|aarch64|UNSUPPORTED)' in PREMIUM_WORKFLOW
    assert 'https://awscli.amazonaws.com/awscli-exe-linux-${aws_package_arch}.zip' in PREMIUM_BOOTSTRAP
    assert 'python3 -m zipfile -e' in PREMIUM_BOOTSTRAP
    assert 'INSTALL_AWS_CLI' in PREMIUM_BOOTSTRAP
    assert '"$stage/awscli-installer/aws/install"' in PREMIUM_BOOTSTRAP
    assert 'chmod 0755 "$stage/awscli-installer/aws/install"' in PREMIUM_BOOTSTRAP
    assert '-i "$stage/aws-cli" -b "$stage/bin"' in PREMIUM_BOOTSTRAP
    assert '"$stage/aws-cli/v2/current/bin/aws"' in PREMIUM_BOOTSTRAP
    assert 'find "$stage/aws-cli" -type f -name aws -perm -u+x' in PREMIUM_BOOTSTRAP
    assert '"$stage/awscli-installer/aws/dist/aws"' in PREMIUM_BOOTSTRAP
    assert 'uname -m 2>/dev/null || true' in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_AWS_CLI_ARCH=' in PREMIUM_BOOTSTRAP


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

def test_premium_secret_error_diagnostics_are_bounded_and_allowlisted():
    assert '2>"$stage/secret-read-error"' in PREMIUM_BOOTSTRAP
    assert 'secret_error_class=UNKNOWN' in PREMIUM_BOOTSTRAP
    assert 'secret_error_class=ACCESS_DENIED' in PREMIUM_BOOTSTRAP
    assert 'secret_error_class=RESOURCE_NOT_FOUND' in PREMIUM_BOOTSTRAP
    assert 'secret_error_class=DECRYPTION_FAILURE' in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_SECRET_ERROR_CLASS=%s' in PREMIUM_BOOTSTRAP
    assert "exit 254" in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_SECRET_ERROR_CLASS=(ACCESS_DENIED|RESOURCE_NOT_FOUND|' in PREMIUM_WORKFLOW
    assert 'head -n 8' in PREMIUM_WORKFLOW
    assert 'cat "$stage/secret-read-error"' not in PREMIUM_BOOTSTRAP


def test_cloud_ws_smoke_is_independent_opt_in_and_bounded():
    # Plain Premium REST/K tests remain the default; no automatic paid WS.
    assert 'ws_seconds:' in PREMIUM_WORKFLOW
    assert 'default: "0"' in PREMIUM_WORKFLOW
    assert 'type: choice' in PREMIUM_WORKFLOW
    for duration in ('"0"', '"10"', '"15"'):
        assert ('- ' + duration) in PREMIUM_WORKFLOW
    assert 'WS_SECONDS: ${{ inputs.ws_seconds }}' in PREMIUM_WORKFLOW
    assert '[[ "$WS_SECONDS" =~ ^(0|10|15)$ ]]' in PREMIUM_WORKFLOW
    assert "'$WS_SECONDS'" in PREMIUM_WORKFLOW
    assert 'if [[ "$#" -ne 6 ]]; then' in PREMIUM_BOOTSTRAP
    assert 'ws_seconds="$6"' in PREMIUM_BOOTSTRAP
    assert '[[ "$ws_seconds" =~ ^(0|10|15)$ ]]' in PREMIUM_BOOTSTRAP
    assert '--ws-seconds "$ws_seconds"' in PREMIUM_BOOTSTRAP
    assert 'RADAR_ADMISSION=BLOCKED' in PREMIUM_BOOTSTRAP
    assert 'LIVE_TRADE=NO' in PREMIUM_BOOTSTRAP


def test_cloud_ws_duration_is_validated_before_remote_network_calls():
    assert PREMIUM_WORKFLOW.index('[[ "$WS_SECONDS" =~ ^(0|10|15)$ ]]') < PREMIUM_WORKFLOW.index('aws ssm send-command')
    assert PREMIUM_BOOTSTRAP.index('[[ "$ws_seconds" =~ ^(0|10|15)$ ]]') < PREMIUM_BOOTSTRAP.index('curl --fail')


def test_cloud_premium_probe_has_exactly_two_explicit_qualification_symbols():
    # The Python probe has a third default symbol. Cloud qualification must not
    # accidentally consume extra provider entitlement or conflate failure modes.
    assert '--symbols 159611.SZ 518880.SH --ws-seconds "$ws_seconds"' in PREMIUM_BOOTSTRAP
    assert '--symbols "$symbols"' not in PREMIUM_BOOTSTRAP
    assert "RADAR_ADMISSION=BLOCKED" in PREMIUM_BOOTSTRAP
    assert "LIVE_TRADE=NO" in PREMIUM_BOOTSTRAP

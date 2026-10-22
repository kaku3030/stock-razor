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
    assert "if: ${{ github.ref == 'refs/heads/main' && inputs.enable_premium_probe == true }}" in PREMIUM_WORKFLOW
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


def test_premium_bootstrap_uses_pinned_aws_sdk_without_exposing_command_output():
    assert 'boto3.__version__ == "1.43.114"' in PREMIUM_BOOTSTRAP
    assert 'botocore.__version__ == "1.43.114"' in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_AWS_SDK=AVAILABLE' in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_AWS_SDK=UNAVAILABLE' in PREMIUM_BOOTSTRAP
    assert 'VERIFY_AWS_SDK' in PREMIUM_BOOTSTRAP
    assert 'get_secret_value(SecretId=secret_id)' in PREMIUM_BOOTSTRAP
    assert 'get-secret-value' not in PREMIUM_BOOTSTRAP
    assert 'awscli.amazonaws.com' not in PREMIUM_BOOTSTRAP
    assert '2>"$stage/secret-read-error"' in PREMIUM_BOOTSTRAP
    assert 'StandardOutputContent' not in PREMIUM_BOOTSTRAP
    assert 'StandardErrorContent' not in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_AWS_SDK=(AVAILABLE|UNAVAILABLE)' in PREMIUM_WORKFLOW

def test_ingress_requires_exact_opt_in():
    assert premium_ingress_enabled("true") is True
    assert premium_ingress_enabled("TRUE") is False
    assert premium_ingress_enabled(None) is False


def test_secret_arn_is_narrow_and_region_bound():
    value = "arn:aws:secretsmanager:ap-northeast-1:888425712426:secret:stock-razor/tickflow/premium-api-key-main-123456"
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
    assert 'TICKFLOW_SECRET_ERROR_CLASS=" + _error_class(exc)' in PREMIUM_BOOTSTRAP
    assert '"AccessDenied": "ACCESS_DENIED"' in PREMIUM_BOOTSTRAP
    assert '"ResourceNotFoundException": "RESOURCE_NOT_FOUND"' in PREMIUM_BOOTSTRAP
    assert '"DecryptionFailure": "DECRYPTION_FAILURE"' in PREMIUM_BOOTSTRAP
    assert '"EndpointConnectionError", "ConnectTimeoutError"' in PREMIUM_BOOTSTRAP
    assert 'secret_error_class="$(sed -nE' in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_SECRET_ERROR_CLASS=%s' in PREMIUM_BOOTSTRAP
    assert "exit 254" in PREMIUM_BOOTSTRAP
    assert 'TICKFLOW_PREMIUM_SECRET_ERROR_CLASS=(ACCESS_DENIED|RESOURCE_NOT_FOUND|' in PREMIUM_WORKFLOW
    assert 'head -n 8' in PREMIUM_WORKFLOW
    assert 'cat "$stage/secret-read-error"' not in PREMIUM_BOOTSTRAP


def test_cloud_ws_smoke_is_independent_opt_in_and_bounded():
    # Single Premium realtime quote is default; no automatic K/depth/WS.
    assert 'ws_seconds:' in PREMIUM_WORKFLOW
    assert 'default: "0"' in PREMIUM_WORKFLOW
    assert 'type: choice' in PREMIUM_WORKFLOW
    for duration in ('"0"', '"10"', '"15"', '"30"', '"60"'):
        assert ('- ' + duration) in PREMIUM_WORKFLOW
    assert 'WS_SECONDS: ${{ inputs.ws_seconds }}' in PREMIUM_WORKFLOW
    assert '[[ "$WS_SECONDS" =~ ^(0|10|15|30|60)$ ]]' in PREMIUM_WORKFLOW
    assert "'$WS_SECONDS'" in PREMIUM_WORKFLOW
    assert 'if [[ "$#" -ne 7 && "$#" -ne 9 ]]; then' in PREMIUM_BOOTSTRAP
    # Original seven-argument Premium quote/REST contract is preserved, and
    # the optional direct-WS scope adds exactly two source integrity hashes.
    assert 'if [[ "$#" -eq 9 ]]; then' in PREMIUM_BOOTSTRAP
    assert '[[ "$quote_only" == false && "$ws_seconds" != 0 ]]' in PREMIUM_BOOTSTRAP
    assert 'quote_only="$7"' in PREMIUM_BOOTSTRAP
    assert 'default: true' in PREMIUM_WORKFLOW
    assert 'QUOTE_ONLY: ${{ inputs.quote_only }}' in PREMIUM_WORKFLOW
    assert 'probe_args+=(--quote-only)' in PREMIUM_BOOTSTRAP
    assert 'ws_seconds="$6"' in PREMIUM_BOOTSTRAP
    assert '[[ "$ws_seconds" =~ ^(0|10|15|30|60|900|3600|7200|9000|14160|16800)$ ]]' in PREMIUM_BOOTSTRAP
    assert '--ws-seconds "$ws_seconds"' in PREMIUM_BOOTSTRAP
    assert 'RADAR_ADMISSION=BLOCKED' in PREMIUM_BOOTSTRAP
    assert 'LIVE_TRADE=NO' in PREMIUM_BOOTSTRAP


def test_cloud_ws_duration_is_validated_before_remote_network_calls():
    assert PREMIUM_WORKFLOW.index('[[ "$WS_SECONDS" =~ ^(0|10|15|30|60)$ ]]') < PREMIUM_WORKFLOW.index('aws ssm send-command')
    assert PREMIUM_BOOTSTRAP.index('[[ "$ws_seconds" =~ ^(0|10|15|30|60|900|3600|7200|9000|14160|16800)$ ]]') < PREMIUM_BOOTSTRAP.index('curl --fail')


def test_cloud_premium_probe_has_exactly_two_explicit_qualification_symbols():
    # The Python probe has a third default symbol. Cloud qualification must not
    # accidentally consume extra provider entitlement or conflate failure modes.
    assert '--symbols 159611.SZ 159209.SZ --ws-seconds "$ws_seconds"' in PREMIUM_BOOTSTRAP
    assert '--symbols "$symbols"' not in PREMIUM_BOOTSTRAP
    assert "RADAR_ADMISSION=BLOCKED" in PREMIUM_BOOTSTRAP
    assert "LIVE_TRADE=NO" in PREMIUM_BOOTSTRAP

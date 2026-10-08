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
    assert "/tmp/run_tickflow_premium_probe.sh" not in PREMIUM_WORKFLOW
    assert "sha256sum -c - >/dev/null" in PREMIUM_WORKFLOW
    assert PREMIUM_WORKFLOW.index("sha256sum -c - >/dev/null") < PREMIUM_WORKFLOW.index(r'bash "\$temp_dir/bootstrap.sh"')


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

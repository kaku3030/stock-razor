"""Static fail-closed contract for guarded TickFlow Premium WS secret reference.

No AWS access, paid provider requests, or order endpoints in these tests.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/probe-tickflow-aws-premium.yml"
BOOTSTRAP = ROOT / "ops/aws/run_tickflow_premium_probe.sh"


def test_blank_reference_is_fixed_name_only_after_explicit_opt_in():
    yaml = WORKFLOW.read_text(encoding="utf-8")
    assert "if: ${{ inputs.enable_premium_probe == true }}" in yaml
    assert "default: false" in yaml
    assert "SECRET_ARN='stock-razor/tickflow/premium'" in yaml
    assert 'if [[ -z "$SECRET_ARN" ]]; then' in yaml
    assert 'if [[ "$SECRET_ARN" != \'stock-razor/tickflow/premium\' ]]; then' in yaml
    assert '[[ "$SECRET_ARN" =~ ^arn:aws:secretsmanager:ap-northeast-1:888425712426:secret:stock-razor/tickflow/premium-' in yaml
    assert "aws ssm send-command" in yaml
    assert 'quote_only' in yaml and 'ws_seconds' in yaml


def test_remote_script_accepts_only_fixed_name_or_original_restricted_arn():
    bash = BOOTSTRAP.read_text(encoding="utf-8")
    assert 'if [[ "$secret_arn" != \'stock-razor/tickflow/premium\' ]]; then' in bash
    assert '[[ "$secret_arn" =~ ^arn:aws:secretsmanager:ap-northeast-1:888425712426:secret:stock-razor/tickflow/premium-' in bash
    assert "TICKFLOW_PREMIUM_PROBE_ENABLED" in bash
    assert "TICKFLOW_PREMIUM_NETWORK_REQUEST_ENABLED" in bash
    assert "VERIFY_REALTIME_EXTRA" in bash
    assert "READ_SECRET" in bash
    assert bash.index("VERIFY_REALTIME_EXTRA") < bash.index("READ_SECRET")
    assert 'source_arbiter_admission' in bash and 'radar_admission' in bash

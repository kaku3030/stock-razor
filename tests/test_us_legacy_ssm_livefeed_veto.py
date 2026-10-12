"""Prevent legacy SSM options from bypassing the US LiveFeed RTH restart guard.

These are source-level security regressions.  CI does not access AWS, OpenD,
provider accounts, services, or real/simulated brokers.
"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROUTER = ROOT / ".github/workflows/aws-ssm-ops.yml"
GUARDED_DEPLOY = ROOT / ".github/workflows/deploy-us-opend-livefeed.yml"


def test_legacy_livefeed_mutation_is_blocked_before_aws_oidc():
    source = LEGACY_ROUTER.read_text(encoding="utf-8")
    guard_marker = "Veto ungoverned LiveFeed stop/restart actions before AWS OIDC"
    aws_marker = "      - name: Configure short-lived AWS credentials"
    assert source.count(guard_marker) == 1
    assert source.count(aws_marker) == 1
    assert source.index(guard_marker) < source.index(aws_marker)
    pre_oidc = source[:source.index(aws_marker)]
    assert re.search(
        r'case "\$REQUESTED_ACTION" in\s*'
        r'us_opend_start_order_probe\|us_livefeed_controlled_restart_probe\)\s*'
        r"echo 'US_LIVEFEED_LEGACY_MUTATION_VETO=BLOCKED' >&2\s*"
        r'exit 2\s*;;',
        pre_oidc,
    ), "Legacy stop/restart selectors must fail closed before AWS credentials"
    assert "inputs.action" in pre_oidc
    assert "id-token: write" in source


def test_veto_covers_real_mutation_cases_not_merely_action_labels():
    source = LEGACY_ROUTER.read_text(encoding="utf-8")
    assert "us_opend_start_order_probe)" in source
    assert 'systemctl stop "$svc"' in source
    assert 'systemctl start "$svc"' in source
    assert "us_livefeed_controlled_restart_probe)" in source
    assert "systemctl restart stock-razor-us-livefeed.service" in source
    assert "      - name: Send fixed command through SSM" in source

    # The separately protected production installer has its own independent
    # runtime guard; this veto must not be mistaken for an EC2 deployment.
    deploy = GUARDED_DEPLOY.read_text(encoding="utf-8")
    assert "python3 scripts/guard_us_livefeed_restart_window.py" in deploy
    assert "AWS-RunShellScript" in deploy

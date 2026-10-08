"""Audit US/CN Source Arbiter from cloud without any write, order or SDK calls."""
from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/audit-data-fabric-cloud-source-shadow.yml").read_text(
    encoding="utf-8"
)


def test_workflow_ssm_is_bounded_and_only_run_manually():
    w = yaml.safe_load(WORKFLOW)
    assert w["permissions"] == {"id-token":"write","contents":"read"}
    assert w["jobs"]["cloud-shadow"]["timeout-minutes"] == 8
    assert "workflow_dispatch:" in WORKFLOW
    assert "cron:" not in WORKFLOW
    assert "ap-northeast-1" in WORKFLOW
    assert "i-01738342af3efac72" in WORKFLOW
    assert "aws-actions/configure-aws-credentials@v4" in WORKFLOW
    assert "AWS-RunShellScript" in WORKFLOW


def test_exact_repo_version_and_existing_cache_only():
    assert 'canonical_sha="$(git rev-parse HEAD)"' in WORKFLOW
    assert 'test "$(git rev-parse HEAD)" = "$expected_sha"' in WORKFLOW
    assert "/opt/stock-razor-mcp/repo" in WORKFLOW
    assert "scripts/probe_cloud_source_arbiter_shadow.py" in WORKFLOW
    assert "STOCK_RAZOR_US_LIVEFEED_STATUS_PATH" in WORKFLOW
    assert "STOCK_RAZOR_CN_EASTMONEY_STATUS_PATH" in WORKFLOW


def test_no_trading_canonical_writer_or_qualification_grants():
    for safety in (
        'p.get("proposals_admitted") == 0',
        'p.get("sources_proven_qualified") == 0',
        'p.get("source_arbiter_runtime_admission") == "BLOCKED"',
        'p.get("canonical_writer_created") is False',
        'p.get("radar_admission") == "BLOCKED"',
        'p.get("live_trade") is False',
        'p.get("data_qualification") == "NOT_VERIFIED"',
        "CLOUD_SOURCE_ARBITER_PRODUCTION_ADMISSION=BLOCKED",
    ):
        assert safety in WORKFLOW
    for forbidden in (
        "systemctl restart", "systemctl stop", "systemctl enable",
        "pip install", "aws secretsmanager", "OpenUSTradeContext",
        "submit_order(", "place_order(", "LIVE_TRADE=YES",
        "aws ec2 run-instances", "aws ssm put-parameter",
    ):
        assert forbidden not in WORKFLOW


def test_ssm_parser_handles_sorted_json_any_first_key():
    assert "grep -E '^[{]' | tail -n1" in WORKFLOW
    assert "CLOUD_SOURCE_ARBITER_AUDIT_EXECUTED=YES" in WORKFLOW
    assert "CLOUD_SOURCE_ARBITER_AUDIT_FAILED" in WORKFLOW


def test_cloud_shadow_requires_two_sample_progress_and_never_claims_feed_slo():
    assert '"source_progress"' in WORKFLOW
    assert '"TWO_SEPARATE_AWS_CACHE_READS_NOT_PROVIDER_SLO"' in WORKFLOW
    assert '"unique_provider_event_delivery_qualified") is False' in WORKFLOW
    assert '"cloud_off_pc_independence") == "NOT_VERIFIED"' in WORKFLOW
    assert 'set(progress.get("cn",{})) == {"159611","518880"}' in WORKFLOW



def test_aws_shadow_binds_read_only_radar_cache_and_rejects_poll_as_increment():
    assert "STOCK_RAZOR_US_RADAR_STATUS_PATH=" in WORKFLOW
    assert 'progress.get("us",{}).get("radar_increment_proven") is False' in WORKFLOW
    assert '"radar_canonical_alignment"' in WORKFLOW
    assert "CLOUD_SOURCE_ARBITER_PRODUCTION_ADMISSION=BLOCKED" in WORKFLOW

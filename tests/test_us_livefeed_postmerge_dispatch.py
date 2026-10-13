"""Contract for cloud-only US LiveFeed read-only automatic audit dispatch."""
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]
FILE=ROOT/".github/workflows/audit-us-livefeed-after-merge.yml"


def _workflow():
    data=yaml.safe_load(FILE.read_text(encoding="utf-8"))
    return data


def test_trigger_exact_main_restricted_to_ssm_router_and_self():
    data=_workflow()
    events=data.get("on",data.get(True))
    assert set(events)=={"push","workflow_dispatch"}
    assert events["push"]["branches"]==["main"]
    assert events["push"]["paths"]==[
        ".github/workflows/aws-ssm-ops.yml",
        ".github/workflows/audit-us-livefeed-after-merge.yml",
    ]
    assert data["permissions"]=={"actions":"write","contents":"read"}
    assert data["concurrency"]["cancel-in-progress"] is False


def test_cloud_audit_dispatch_has_no_aws_credentials_broker_or_trade_mutations():
    text=FILE.read_text(encoding="utf-8")
    data=_workflow()
    steps=data["jobs"]["dispatch"]["steps"]
    assert len(steps)==2
    assert data["jobs"]["dispatch"]["timeout-minutes"]==3
    assert text.count('test "$(gh api') == 1
    assert 'if [[ "$main_sha" != "$GITHUB_SHA" ]]' in text
    assert 'gh workflow run aws-ssm-ops.yml --repo "$GITHUB_REPOSITORY" --ref main -f action=us_livefeed_status' in text
    assert 'US_LIVEFEED_POSTMERGE_DISPATCH=SUBMITTED_NOT_VERIFIED' in text
    assert "RADAR_ADMISSION=BLOCKED" in text
    assert "SOURCE_ARBITER_ADMISSION=BLOCKED" in text
    assert "PAPER_AUTO_READY=NO" in text
    assert "LIVE_TRADE=NO" in text
    assert "TRADE_EXECUTION=NO" in text
    forbidden=("aws-actions/configure-aws-credentials","aws ssm","systemctl restart",
               "OpenUSTradeContext","OpenSecTradeContext","BROKER_ORDER=",
               "LIVE_TRADE=YES","RADAR_ADMISSION=READY",
               "curl -","wget ")
    assert all(x not in text for x in forbidden)

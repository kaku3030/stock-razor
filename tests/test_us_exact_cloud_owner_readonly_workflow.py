"""GitHub-hosted US exact-main cloud read-only audit owner/SSM gates."""
from pathlib import Path

import yaml

WORKFLOW=Path(__file__).resolve().parents[1]/".github/workflows/probe-us-cloud-exact.yml"
TEXT=WORKFLOW.read_text(encoding="utf-8")
SPEC=yaml.safe_load(TEXT)


def test_owner_comment_and_manual_dispatch_are_fixed_and_fail_closed():
    events=SPEC.get("on",SPEC.get(True))
    assert set(events)=={"issue_comment","workflow_dispatch"}
    assert events["issue_comment"]["types"]==["created"]
    job=SPEC["jobs"]["probe"]
    for guard in (
        "github.ref == 'refs/heads/main'",
        "github.event_name == 'workflow_dispatch'",
        "github.event.issue.number == 708",
        "github.event.issue.pull_request != null",
        "github.actor == github.repository_owner",
        "github.event.comment.user.login == github.repository_owner",
        "github.event.comment.author_association == 'OWNER'",
        "github.event.comment.body == '/stock-razor us-exact-cloud read-only'",
    ):
        assert guard in job["if"]
    assert SPEC["permissions"]=={"id-token":"write","contents":"read"}
    assert SPEC["concurrency"]["cancel-in-progress"] is False


def test_exact_main_owner_gate_must_precede_oidc_and_ssm():
    steps=SPEC["jobs"]["probe"]["steps"]
    name=next(i for i,s in enumerate(steps) if s.get("name","").startswith("Authorize owner comment"))
    oidc=next(i for i,s in enumerate(steps) if str(s.get("uses","")).startswith("aws-actions/configure-aws-credentials"))
    ssm=next(i for i,s in enumerate(steps) if s.get("name")=="Run bounded US-only read-only probe")
    assert name<oidc<ssm
    guard=steps[name]["run"]
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in guard
    assert 'test "$GITHUB_REF" = refs/heads/main' in guard
    assert 'gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main"' in guard
    assert '"$GITHUB_EVENT_PATH" >/dev/null' in guard
    for i in (".sender.login == $owner",".comment.user.login == $owner",
              '.comment.author_association == "OWNER"',
              '.comment.body == "/stock-razor us-exact-cloud read-only"'):
        assert i in guard
    s=steps[ssm]["run"]
    assert s.count('gh api "repos/${GITHUB_REPOSITORY}/git/ref/heads/main"')==2
    assert "aws ssm send-command" in s
    assert s.index('test "$(gh api') < s.index("aws ssm send-command")


def test_fixed_inputs_private_output_and_no_admission():
    steps=SPEC["jobs"]["probe"]["steps"]
    run=next(x for x in steps if x.get("name")=="Run bounded US-only read-only probe")
    assert run["env"]["DURATION_SECONDS"]=="${{ github.event_name == 'issue_comment' && '30' || inputs.duration_seconds }}"
    assert "US.AMD,US.NVDA,US.TSLA" in run["env"]["SYMBOLS"]
    txt=run["run"]
    assert "scripts/probe_us_cloud_exact.py" in txt
    assert "--ssm-summary-only" in txt
    assert "US_EXACT_CLOUD_RUNTIME_SHA=NOT_VERIFIED" in txt
    assert "US_EXACT_CLOUD_PROBE_SANITIZED=" in txt
    assert "RADAR_ADMISSION=BLOCKED" in txt
    assert "SOURCE_ARBITER_ADMISSION=BLOCKED" in txt
    assert "LIVE_TRADE=NO" in txt
    for forbidden in ("OpenUSTradeContext", "OpenSecTradeContext", "place_order(",
                       "systemctl restart", "systemctl stop",
                       "unlock_trade(", "LIVE_TRADE=YES"):
        assert forbidden not in TEXT

"""Owner-only AWS TickFlow read-only comment route must remain fail-closed."""
from copy import deepcopy
from pathlib import Path

from scripts.authorize_cloud_ops_audit_comment import authorized_owner_comment

REPO = "kaku3030/stock-razor"


def event(pr=658, body="/stock-razor tickflow-audit read-only"):
    return {
        "action": "created",
        "repository": {"full_name": REPO},
        "sender": {"login": "kaku3030"},
        "issue": {"number": pr, "pull_request": {"url": "not_used"}},
        "comment": {
            "id": 884211,
            "body": body,
            "author_association": "OWNER",
            "user": {"login": "kaku3030"},
        },
    }


def allowed(value):
    return authorized_owner_comment(
        value, actor="kaku3030", repository=REPO,
        event_name="issue_comment",
    )


def test_two_fixed_owner_only_readonly_audits_are_separate():
    assert allowed(event())
    assert allowed(event(665, "/stock-razor aws-audit read-only"))
    assert not allowed(event(665))
    assert not allowed(event(658, "/stock-razor aws-audit read-only"))
    assert not allowed(event(659))


def test_actor_sender_author_association_and_command_are_all_required():
    original = event()
    assert not authorized_owner_comment(
        original, actor="attacker", repository=REPO,
        event_name="issue_comment",
    )
    for container, key, value in (
        ("sender", "login", "attacker"),
        ("repository", "full_name", "attacker/stock-razor"),
        ("comment", "author_association", "CONTRIBUTOR"),
        ("comment", "body", "/stock-razor tickflow-audit read-only\n"),
        ("comment", "id", False),
        ("issue", "number", True),
        ("issue", "pull_request", None),
    ):
        modified = deepcopy(original)
        modified[container][key] = value
        assert not allowed(modified)
    assert not authorized_owner_comment(
        original, actor="kaku3030", repository=REPO,
        event_name="workflow_dispatch",
    )


def test_tickflow_workflow_has_preauth_main_and_ssm_guards():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/audit-cn-tickflow-live-research.yml").read_text(encoding="utf-8")
    assert "  issue_comment:\n    types: [created]" in workflow
    assert "github.event.issue.number == 658" in workflow
    assert "github.event.comment.author_association == 'OWNER'" in workflow
    assert "github.event.comment.body == '/stock-razor tickflow-audit read-only'" in workflow
    assert "python3 scripts/authorize_cloud_ops_audit_comment.py" in workflow
    assert workflow.index("Authorize owner-only comment before AWS OIDC") < workflow.index("aws-actions/configure-aws-credentials")
    assert "ref: ${{ github.sha }}" in workflow
    assert workflow.count("test \"$head\" = \"$GITHUB_SHA\"") >= 2
    assert "Verify two isolated AWS snapshots 65 seconds apart" in workflow
    assert "assert d.get(\"radar_admission\")==\"BLOCKED\"" in workflow
    assert "assert d.get(\"live_trade\")==\"NO\"" in workflow


def test_untrusted_comments_cannot_consume_workflow_concurrency():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/audit-cn-tickflow-live-research.yml").read_text(encoding="utf-8")
    assert "\nconcurrency:\n" not in workflow
    assert "jobs:\n  audit:\n" in workflow
    assert "    concurrency:\n      group: cn-tickflow-research-worker" in workflow
    assert workflow.index("jobs:\n  audit:\n") < workflow.index("    concurrency:\n") < workflow.index("    if: >-")
    assert workflow.count("cancel-in-progress: false") == 1
    assert "github.event.issue.number == 658" in workflow


def test_paid_worker_deploy_and_two_snapshot_audit_share_non_cancelling_lock():
    root = Path(__file__).resolve().parents[1]
    audit = (root / ".github/workflows/audit-cn-tickflow-live-research.yml").read_text(encoding="utf-8")
    deploy = (root / ".github/workflows/deploy-cn-tickflow-research.yml").read_text(encoding="utf-8")
    group = "group: cn-tickflow-research-worker"
    assert audit.count(group) == 1
    assert deploy.count(group) == 1
    assert "    concurrency:" in audit  # job-level: untrusted comments never lock
    assert "jobs:\n  audit:\n" in audit
    assert audit.index("    concurrency:") < audit.index("    if: >-")
    assert "concurrency:\n  group: cn-tickflow-research-worker" in deploy
    assert "cancel-in-progress: false" in audit
    assert "cancel-in-progress: false" in deploy
    # A GitHub concurrency group allows only one running audit/deploy.
    # It is NOT a provider-health, closure or realtime data assertion.
    assert "Verify two isolated AWS snapshots 65 seconds apart" in audit
    assert "RADAR_ADMISSION: BLOCKED" not in audit  # gate checked via audited output
    assert "approve_paid_tickflow_ingestion" in deploy

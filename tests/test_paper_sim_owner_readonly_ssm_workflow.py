"""Owner-only main-pinned Paper SIM account observation through existing AWS SSM."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

FILE=Path(__file__).resolve().parents[1]/".github/workflows/aws-ssm-sim-account-discovery.yml"
TEXT=FILE.read_text(encoding="utf-8")
DOC=yaml.safe_load(TEXT)
JOB=DOC["jobs"]["read-only-sim-account-discovery"]


def test_owner_only_comment_scope_and_existing_manual_dispatch():
    trigger=DOC.get("on",DOC.get(True))
    assert set(trigger)=={"workflow_dispatch","issue_comment"}
    assert trigger["issue_comment"]["types"]==["created"]
    assert "github.ref == 'refs/heads/main'" in JOB["if"]
    for guard in (
        "github.event.issue.number == 698",
        "github.event.issue.pull_request != null",
        "github.actor == github.repository_owner",
        "github.event.comment.user.login == github.repository_owner",
        "github.event.comment.author_association == 'OWNER'",
        "github.event.comment.body == '/stock-razor paper-sim-audit read-only'",
    ):
        assert guard in JOB["if"]
    assert DOC["permissions"]=={"id-token":"write","contents":"read"}
    assert DOC["concurrency"]["cancel-in-progress"] is False


def test_exact_main_and_owner_event_gate_precede_oidc():
    steps=JOB["steps"]
    names=[x["name"] for x in steps]
    assert names.index("Checkout immutable main before AWS identity") < names.index(
        "Verify owner event, main source and zero trade mutation before AWS OIDC"
    ) < names.index("Configure short-lived AWS credentials")
    checkout=steps[names.index("Checkout immutable main before AWS identity")]
    assert checkout["with"]["ref"]=="${{ github.sha }}"
    assert checkout["with"]["persist-credentials"] is False
    run=steps[names.index("Verify owner event, main source and zero trade mutation before AWS OIDC")]["run"]
    assert 'test "$GITHUB_REF" = refs/heads/main' in run
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in run
    assert "git/ref/heads/main" in run
    assert 'jq -e --arg owner "$GITHUB_REPOSITORY_OWNER"' in run
    for value in ("PAPER_AUTO_READY=NO","RADAR_ADMISSION=BLOCKED",
                  "LIVE_TRADE=NO","TRADE_EXECUTION=NO"):
        assert value in run


def test_private_sim_only_readback_retains_no_trade_mutation():
    assert "ft.TrdEnv.SIMULATE" in TEXT
    assert "get_acc_list()" in TEXT
    assert "accinfo_query(" in TEXT
    assert "position_list_query(" in TEXT
    assert "order_list_query(" in TEXT
    assert "history_order_list_query(" in TEXT
    assert "sim_native_fills: \"UNSUPPORTED_BY_OPEND\"" in TEXT
    assert 'paper_preflight: "BLOCKED"' in TEXT
    assert "RAW SSM STDOUT" not in TEXT.upper()
    assert "OpenSecTradeContext" in TEXT
    for bad in ("place_order(", "modify_order(", "unlock_trade(", "cancel_order(",
                "TrdEnv.REAL", "sim_acc_id=", "echo $AWS_SECRET"):
        assert bad not in TEXT
    assert "StandardErrorContent" not in TEXT


@pytest.mark.parametrize("actor,body,association,pr_number,allowed",[
    ("kaku3030","/stock-razor paper-sim-audit read-only","OWNER",698,True),
    ("impostor","/stock-razor paper-sim-audit read-only","OWNER",698,False),
    ("kaku3030","/stock-razor paper-sim-audit read-only ","OWNER",698,False),
    ("kaku3030","/stock-razor paper-sim-audit read-only","COLLABORATOR",698,False),
    ("kaku3030","/stock-razor paper-sim-audit read-only","OWNER",699,False),
])
def test_owner_jq_payload_is_fail_closed(actor,body,association,pr_number,allowed):
    if shutil.which("jq") is None:
        pytest.skip("jq is present on GitHub hosted Ubuntu")
    payload={"issue":{"number":pr_number,"pull_request":{}},
             "sender":{"login":actor},
             "comment":{"user":{"login":actor},"author_association":association,"body":body}}
    query=('(.issue.number == 698) and (.issue.pull_request != null) and '
           '(.sender.login == $owner) and (.comment.user.login == $owner) and '
           '(.comment.author_association == "OWNER") and '
           '(.comment.body == "/stock-razor paper-sim-audit read-only")')
    result=subprocess.run(["jq","-e","--arg","owner","kaku3030",query],input=json.dumps(payload),text=True,capture_output=True,check=False)
    assert (result.returncode==0) is allowed

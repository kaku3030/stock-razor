"""Fast topic-triggered recovery and authenticated owner discussion sync checks."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest
from scripts.stock_razor_fast_sync import (
    PREFIX, FastSyncError, parse_comment, route_discussion, SCHEMA
)
SHA = "a" * 40
URL = "https://github.com/kaku3030/stock-razor/pull/936"


def sample():
    return {
        "repository": {"full_name": "kaku3030/stock-razor"},
        "issue": {"number": 924},
        "comment": {
            "id": 6269000123,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "author_association": "OWNER",
            "user": {"login": "kaku3030"},
            "body": PREFIX + json.dumps({
                "topic": "strategy", "state": "DECIDED",
                "summary": "统一 D1、1H、15m 的研究流程，未闭合K线不得触发交易",
                "evidence_url": URL, "source_sha": SHA,
            }, ensure_ascii=False),
        },
    }


@pytest.mark.parametrize("message,topic", [
    ("今晚美股 OpenD 数据怎么了", "us"),
    ("TickFlow A股行情是否同步", "cn"),
    ("我们的15分钟和日线策略", "strategy"),
    ("查询 STOCK RAZOR 最新主线", "engineering"),
    ("我新开一个雷达窗口", "engineering"),
    ("我的交易组合", "portfolio"),
    ("政策美联储美股", "policy"),
    ("Get US NVDA 15m Radar", "us"),
])
def test_topic_routes_trigger_latest_repo_and_context(message, topic):
    report = route_discussion(message)
    assert report["action"] == "FETCH_CURRENT_MAIN_AND_CONTEXT"
    assert topic in report["topics"]
    assert "STOCK_RAZOR_MCP_CONTEXT_MANAGER_SENTINEL" in report["entrypoints"]
    assert "GITHUB_ISSUE_924_OWNER_SYNC_COMMENTS" in report["entrypoints"]
    assert report["no_access_state"] == "SYNC_NOT_VERIFIED"


def test_irrelevant_message_does_not_query_private_project():
    report = route_discussion("我今天想吃什么菜")
    assert report["action"] == "NO_PROJECT_TRIGGER"
    assert report["topics"] == []


def test_project_window_continuation_without_repeating_key_word():
    report = route_discussion("继续", stock_razor_window=True)
    assert report["action"] == "FETCH_CURRENT_MAIN_AND_CONTEXT"


def test_valid_owner_issue_comment_becomes_radar_event_without_raw_body():
    packet = parse_comment(sample())
    assert packet["schema"] == SCHEMA
    assert packet["status"] == "ACCEPTED"
    assert packet["event_type"] == "radar_sync"
    assert packet["source"] == "radar"
    assert packet["event_id"] == "github:sync:6269000123"
    assert packet["payload"]["topic"] == "strategy"
    assert packet["payload"]["source_sha"] == SHA
    assert packet["ttl_seconds"] == 259200
    assert packet["delivery_receipt"] == "NOT_VERIFIED_UNTIL_SSM_READBACK"


def test_eng_project_decision_routes_to_priorities():
    e = sample()
    payload = json.loads(e["comment"]["body"][len(PREFIX):])
    payload.update(topic="engineering", state="IN_PROGRESS")
    e["comment"]["body"] = PREFIX + json.dumps(payload, ensure_ascii=False)
    packet = parse_comment(e)
    assert packet["event_type"] == "priorities_sync"
    assert packet["source"] == "engineering"


@pytest.mark.parametrize("mutator", [
    lambda e: e["repository"].update(full_name="someone/fork"),
    lambda e: e["issue"].update(number=9240),
    lambda e: e["comment"]["user"].update(login="attacker"),
    lambda e: e["comment"].update(author_association="NONE"),
    lambda e: e["comment"].update(body="普通评论，不是同步事件"),
    lambda e: e["comment"].update(id="bad"),
    lambda e: e["comment"].update(created_at="2037-01-01T00:00:00Z"),
])
def test_untrusted_source_never_enters_context_manager(mutator):
    e = sample()
    mutator(e)
    with pytest.raises(FastSyncError):
        parse_comment(e)


@pytest.mark.parametrize("patch", [
    {"topic": "evil"},
    {"source_sha": "main"},
    {"evidence_url": "https://example.org"},
    {"summary": "token=abc123 long important statement"},
    {"summary": "short"},
    {"summary": "这是一个\n含换行的长说明"},
    {"new_secret": "secret"},
])
def test_payload_invalidity_fails_closed(patch):
    e = sample()
    payload = json.loads(e["comment"]["body"][len(PREFIX):])
    payload.update(patch)
    e["comment"]["body"] = PREFIX + json.dumps(payload, ensure_ascii=False)
    with pytest.raises(FastSyncError):
        parse_comment(e)


def test_cli_parse_no_secret_logging(tmp_path):
    input_file = tmp_path / "event.json"
    input_file.write_text(json.dumps(sample(), ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, "scripts/stock_razor_fast_sync.py",
                        "--parse-comment", str(input_file)], capture_output=True, text=True)
    assert p.returncode == 0
    report = json.loads(p.stdout)
    assert report["status"] == "ACCEPTED"
    assert "NOT_VERIFIED" in report["delivery_receipt"]


def test_workflow_only_trusted_issue_comment_and_existing_context_store():
    text = Path(".github/workflows/stock-razor-fast-context-sync.yml").read_text(encoding="utf-8")
    assert "  issue_comment:" in text
    assert "github.event.issue.number == 924" in text
    assert "github.event.comment.user.login == 'kaku3030'" in text
    assert "github.event.comment.author_association == 'OWNER'" in text
    assert "test \"$GITHUB_ACTOR\" = kaku3030" in text
    assert "contents: read" in text
    assert "id-token: write" in text
    assert "contents: write" not in text
    assert "github.event.comment.body" not in text
    assert "--parse-comment \"$GITHUB_EVENT_PATH\"" in text
    assert "/var/lib/stock-razor/context-manager/events.jsonl" in text
    assert "record_context_event.py" in text
    assert "CONTEXT_DISCUSSION_SYNC=PASS" in text


def test_workflow_uses_existing_fixed_ssm_target_and_rejects_untrusted_subprocess():
    import yaml
    workflow = yaml.safe_load(Path(".github/workflows/stock-razor-fast-context-sync.yml").read_text(encoding="utf-8"))
    step = next(s["run"] for s in workflow["jobs"]["publish"]["steps"]
                if s.get("name") == "Record allowlisted event in existing cloud Context Manager")
    assert "i-01738342af3efac72" in workflow["jobs"]["publish"]["env"]["TARGET_INSTANCE_ID"]
    assert "AWS-RunShellScript" in step
    assert "base64 -w0" in step
    assert "payload_b64" in step
    assert "StandardOutputContent" in step
    assert "CONTEXT_DISCUSSION_RECEIPT=SSM_RECORDED_OR_DUPLICATE" in step



def test_latest_discussion_fast_pointer_is_known_to_all_project_agents():
    from scripts.stock_razor_fast_sync import route_discussion
    routes = route_discussion("交易 雷达 OpenD 策略")
    assert "GITHUB_FAST_POINTER_COMMENT_6269031171" in routes["entrypoints"]
    for pathname in (
        "AGENTS.md",
        ".claude/skills/stock-razor-self-improvement/SKILL.md",
        ".github/copilot-instructions.md",
        "docs/architecture/stock-razor-fast-cross-window-sync.md",
    ):
        contents = Path(pathname).read_text(encoding="utf-8")
        assert "6269031171" in contents, pathname
    docs = Path("AGENTS.md").read_text(encoding="utf-8")
    assert "同步" in docs and "去敏" in docs
    assert "未打开的新聊天" in docs

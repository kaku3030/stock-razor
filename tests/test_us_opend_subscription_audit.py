"""Offline contract tests for safe OpenD quota inspection in AWS SSM Ops."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/aws-ssm-ops.yml").read_text(encoding="utf-8")


def _source() -> str:
    start = WORKFLOW.index("            us_opend_subscription_audit)\n")
    end = WORKFLOW.index("            futures_opend_snapshot_probe)\n", start)
    block = WORKFLOW[start:end]
    return block.split("          import json\n", 1)[1].split("          PY\n", 1)[0]


def _parser():
    source = "import json\n" + _source()
    # Workflow embeds Python under a fixed 10-space heredoc indentation.
    import textwrap
    tree = ast.parse(textwrap.dedent(source))
    function = next(
        x for x in tree.body
        if isinstance(x, ast.FunctionDef) and x.name == "parse_subscription"
    )
    tracked = ("US.AMD", "US.NVDA", "US.TSLA", "US.AAPL", "US.QQQ",
               "US.CIEN", "US.AAOI", "US.LITE", "US.GLDM")
    scope = {"tracked": tracked}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<audit>", "exec"), scope)
    return scope["parse_subscription"]


def test_workflow_audit_is_read_only_and_does_not_restart_feed():
    script = _source()
    assert "query_subscription(is_all_conn=True)" in script
    assert "SUBSCRIPTION_CHANGES=NONE" in WORKFLOW
    assert "RADAR_ADMISSION=BLOCKED" in script
    assert "SOURCE_ARBITER_ADMISSION=BLOCKED" in script
    assert "LIVE_TRADE=NO" in script
    assert "ctx.subscribe(" not in script
    assert "ctx.unsubscribe(" not in script
    assert "systemctl restart" not in script
    assert "print(data)" not in script
    assert "str(data)" not in script


def test_audit_parses_only_allowlisted_aggregates_and_tracked_symbols():
    parse = _parser()
    response = parse({
        "sub_list": {"K_1M": ["US.AMD", "US.AAOI", "US.UNKNOWN", "HK.00700"],
                     "QUOTE": ["US.QQQ"], "ACCOUNT": ["secret"]},
        "sub_num": {"total_used": 8, "remain": 12, "account_id": "sensitive",
                    "used": -1, "limit": 999999999},
        "credentials": "should_not_appear",
    })
    assert response["query_status"] == "PASS"
    assert response["quota_verified"] is True
    assert response["subscription_capacity"] == {"total_used": 8, "remain": 12}
    assert response["subscribed_tracked"] == ["US.AAOI", "US.AMD", "US.QQQ"]
    assert "US.UNKNOWN" not in str(response)
    assert "sensitive" not in str(response)
    assert "secret" not in str(response)


def test_audit_unknown_quota_does_not_infer_available_slots():
    parse = _parser()
    response = parse({"sub_list": {"K_1M": ["US.AMD"]}, "sub_num": {"remain": 5}})
    assert response["query_status"] == "PASS"
    assert response["quota_verified"] is False
    assert response["subscription_capacity"] == "UNKNOWN"
    assert response["subscribed_tracked"] == ["US.AMD"]
    assert parse("bad response")["query_status"] == "UNRECOGNIZED_RESPONSE"

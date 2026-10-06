from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/aws-ssm-ops.yml").read_text()


def _probe_block() -> str:
    start = WORKFLOW.index("            us_opend_userinfo_qot_right_probe)")
    end = WORKFLOW.index("            futures_opend_snapshot_probe)", start)
    return WORKFLOW[start:end]


def _embedded_python() -> str:
    block = _probe_block()
    marker = "HOME=/root /opt/stock-razor-opend-client/venv/bin/python - <<'PY'"
    start = block.index(marker)
    start = block.index("\n", start) + 1
    end = block.index("\n          PY", start)
    return "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in block[start:end].splitlines()
    )


def test_userinfo_qot_right_probe_is_exposed_as_read_only_action():
    assert "- us_opend_userinfo_qot_right_probe" in WORKFLOW
    block = _probe_block()
    assert "ctx.get_user_info([ft.UserInfoField.QOTRIGHT])" in block
    assert '"probe":"us_opend_userinfo_qot_right"' in block
    assert '"us_qot_right":"UNKNOWN"' in block
    assert 'data.get("us_qot_right","UNKNOWN")' in block


def test_userinfo_qot_right_probe_requests_only_quote_right_field():
    block = _probe_block()
    assert "ft.UserInfoField.QOTRIGHT" in block
    assert "UserInfoField.BASIC" not in block
    assert "UserInfoField.API" not in block
    assert "UserInfoField.WEBKEY" not in block
    assert "nick_name" not in block
    assert "avatar_url" not in block
    assert "user_id" not in block
    assert "web_key" not in block
    assert "api_level" not in block


def test_userinfo_qot_right_probe_never_mutates_permissions_or_subscriptions():
    block = _probe_block()
    assert ".subscribe(" not in block
    assert ".unsubscribe(" not in block
    assert ".set_handler(" not in block
    assert "request_highest_quote_right" not in block
    assert "OpenUSTradeContext" not in block
    assert "OpenSecTradeContext" not in block


def test_userinfo_qot_right_probe_cannot_promote_delivery_or_trading():
    block = _probe_block()
    assert '"delivery_mode":"UNKNOWN"' in block
    assert '"radar_admission":"BLOCKED"' in block
    assert '"live_trade":False' in block
    assert 'print("DELIVERY_MODE=UNKNOWN")' in block
    assert 'print("RADAR_ADMISSION=BLOCKED")' in block
    assert 'print("LIVE_TRADE=NO")' in block
    assert '"delivery_mode":"REALTIME"' not in block


def test_userinfo_qot_right_probe_embedded_python_compiles():
    compile(
        _embedded_python(),
        "aws-ssm-ops.yml:userinfo-qot-right-probe",
        "exec",
    )


def test_workflow_yaml_parses():
    parsed = yaml.safe_load(WORKFLOW)
    assert parsed["name"]

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github/workflows/aws-ssm-ops.yml').read_text()


def _probe_block() -> str:
    start = WORKFLOW.index('            us_opend_qot_right_notify_probe)')
    end = WORKFLOW.index('            futures_opend_snapshot_probe)', start)
    return WORKFLOW[start:end]


def _embedded_python() -> str:
    block = _probe_block()
    marker = "HOME=/root /opt/stock-razor-opend-client/venv/bin/python - <<'PY'"
    start = block.index(marker)
    start = block.index('\n', start) + 1
    end = block.index('\n          PY', start)
    return '\n'.join(
        line[10:] if line.startswith('          ') else line
        for line in block[start:end].splitlines()
    )


def test_qot_right_probe_is_exposed_as_read_only_action():
    assert '- us_opend_qot_right_notify_probe' in WORKFLOW
    block = _probe_block()
    assert 'SysNotifyHandlerBase' in block
    assert 'SysNotifyType.QOT_RIGHT' in block
    assert 'us_qot_right' in block
    assert 'observed.wait(15)' in block
    assert 'NO_QOT_RIGHT_NOTIFICATION_WITHIN_WINDOW' in block


def test_qot_right_probe_never_subscribes_or_requests_quote_right():
    block = _probe_block()
    assert '.subscribe(' not in block
    assert '.unsubscribe(' not in block
    assert 'request_highest_quote_right' not in block
    assert 'OpenUSTradeContext' not in block
    assert 'OpenSecTradeContext' not in block


def test_qot_right_probe_cannot_promote_delivery_or_trading():
    block = _probe_block()
    assert '"delivery_mode":"UNKNOWN"' in block
    assert '"radar_admission":"BLOCKED"' in block
    assert '"live_trade":False' in block
    assert 'print("DELIVERY_MODE=UNKNOWN")' in block
    assert 'print("RADAR_ADMISSION=BLOCKED")' in block
    assert 'print("LIVE_TRADE=NO")' in block
    assert 'delivery_mode":"REALTIME' not in block


def test_qot_right_probe_only_logs_quote_right_fields_from_notify_message():
    block = _probe_block()
    assert 'endswith("_qot_right")' in block
    assert 'quote_right_fields' in block
    assert 'user_id' not in block
    assert 'login_user_id' not in block


def test_qot_right_probe_embedded_python_compiles():
    compile(_embedded_python(), 'aws-ssm-ops.yml:qot-right-probe', 'exec')


def test_workflow_yaml_parses():
    parsed = yaml.safe_load(WORKFLOW)
    assert parsed['name']
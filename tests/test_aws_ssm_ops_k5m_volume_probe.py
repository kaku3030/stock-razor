from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "aws-ssm-ops.yml"


def test_k5m_volume_probe_is_registered_and_fail_closed():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "- us_opend_k5m_volume_probe" in text
    assert "us_opend_k5m_volume_probe)" in text
    assert '"probe":"us_opend_k5m_volume"' in text
    assert '"purpose":"DIAGNOSTIC_ONLY"' in text
    assert '"delivery_mode":"UNKNOWN"' in text
    assert '"radar_admission":"BLOCKED"' in text
    assert '"live_trade":False' in text
    assert 'print("RADAR_ADMISSION=BLOCKED")' in text
    assert 'print("LIVE_TRADE=NO")' in text


def test_k5m_volume_probe_compares_values_without_changing_canonical_rules():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'aggregate_bars(closed,"5m"' in text
    assert '"derived_volume":dvol' in text
    assert '"native_volume":nvol' in text
    assert '"volume_ratio":vr' in text
    assert '"derived_turnover":dto' in text
    assert '"native_turnover":nto' in text
    assert '"turnover_mismatches":turnover_mismatch' in text
    assert "dtime(9,30) < stamp.time() <= dtime(16,0)" in text


def test_k5m_volume_probe_inline_python_compiles_and_workflow_parses():
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"us_opend_k5m_volume_probe\).*?<<'PY'\n(?P<code>.*?)\n\s*PY\n\s*REMOTE",
        text,
        flags=re.DOTALL,
    )
    assert match is not None
    code = "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in match.group("code").splitlines()
    )
    compile(code, "us_opend_k5m_volume_probe", "exec")
    yaml.safe_load(text)

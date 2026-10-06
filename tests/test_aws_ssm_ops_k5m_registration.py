from pathlib import Path


def test_k5m_probe_is_registered_and_has_independent_case_branch():
    text = Path('.github/workflows/aws-ssm-ops.yml').read_text().replace('\r\n', '\n')
    assert '          - us_opend_k1m_continuity_probe\n          - us_opend_k5m_probe\n' in text
    assert '            us_opend_k5m_probe)\n' in text
    assert '              ;;\n            us_opend_k1m_continuity_probe)\n' in text
    assert '`r`n' not in text

"""Guard: OpenD SSM stdout parser must split actual newline, not literal slash-n."""
from pathlib import Path


def test_ssm_benchmark_jq_line_split_uses_real_newline_escape():
    text = Path(".github/workflows/benchmark-opend-native-klines-readonly.yml").read_text("utf-8")
    assert 'split("\\n")' in text
    assert 'split("\\\\n")' not in text
    assert 'EXPECTED_EXACTLY_ONE_SANITIZED_JSON_REPORT' in text
    assert 'OPEND_SUBSCRIPTION_CHANGES=NONE' in text
    assert 'RADAR_ADMISSION=BLOCKED' in text

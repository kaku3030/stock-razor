"""Ensure SSM stdout parser handles actual newline-separated SDK logs."""
from pathlib import Path


def test_native_kline_workflow_parses_actual_newlines():
    src = Path(".github/workflows/benchmark-opend-native-klines-readonly.yml").read_text("utf-8")
    assert r'split("\n")[]' in src
    assert r'split("\\n")[]' not in src
    assert "EXPECTED_EXACTLY_ONE_SANITIZED_JSON_REPORT" in src
    assert "PRIVATE_SSM_STDERR_WITHHELD=YES" in src

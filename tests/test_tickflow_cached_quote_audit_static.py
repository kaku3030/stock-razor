"""No paid re-run is permitted just to recover AWS sanitized quote evidence."""
from pathlib import Path


def test_existing_quote_cache_probe_is_readonly_and_inert():
    workflow=Path(".github/workflows/audit-existing-tickflow-quote-cache.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "expected_probe_sha:" in workflow
    assert "last-sanitized-probe.json" in workflow
    assert "TICKFLOW_CACHE_AUDIT_SANITIZED=" in workflow
    assert "read_text(encoding=" in workflow
    assert "get-secret-value" not in workflow
    assert "TICKFLOW_API_KEY" not in workflow
    assert "quotes.get" not in workflow
    assert "klines.get" not in workflow
    assert "import tickflow" not in workflow
    assert "subscribe(" not in workflow
    assert "aws ssm send-command" in workflow
    assert "aws ssm get-command-invocation" in workflow
    assert "aws s3 cp" not in workflow
    assert 'echo "$output"' not in workflow
    assert "StandardErrorContent" not in workflow
    assert "RADAR_ADMISSION=ENABLED" not in workflow
    assert "LIVE_TRADE=YES" not in workflow


def test_sanitized_cache_evidence_cannot_be_mistaken_for_tickflow_admission():
    wf=Path(".github/workflows/audit-existing-tickflow-quote-cache.yml").read_text(encoding="utf-8")
    assert '"data_admission": "BLOCKED"' in wf
    assert '"source_arbiter_admission": "BLOCKED"' in wf
    assert '"live_trade": "NO"' in wf
    assert '"provider_requests": 0' in wf
    assert "revision_matches" in wf
    assert "CACHE_REVISION_MISMATCH" in wf
    assert "CACHED_QUOTE_OPERATION_NOT_FRESHNESS_PROOF" in wf
    assert '"request_scope" in' not in wf  # Old sanitized cache may lack field.
    assert "scope_field" in wf

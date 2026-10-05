from pathlib import Path


WORKFLOW = Path(".github/workflows/audit-futures-pc-off.yml")


def test_pc_off_workflow_uses_tested_heartbeat_parser_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "extract_futures_heartbeat_payloads(evidence_file)" in workflow
    assert "re.search(" not in workflow
    assert "json.loads(" not in workflow

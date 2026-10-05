from pathlib import Path


WORKFLOW = Path(".github/workflows/audit-futures-pc-off.yml")


def test_pc_off_workflow_uses_tested_heartbeat_parser_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "extract_futures_heartbeat_payloads([evidence_text])" in workflow
    assert "re.search(" not in workflow
    assert "json.loads(" not in workflow


def test_pc_off_embedded_python_compiles():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = "python - <<'PY'\n"
    script = workflow.split(marker, 1)[1].split("\n          PY", 1)[0]
    script = "\n".join(line[10:] if line.startswith("          ") else line for line in script.splitlines())
    script = script.replace("${{ github.run_id }}", "12345")
    compile(script, str(WORKFLOW), "exec")


def test_pc_off_timestamp_parser_trims_dispatch_whitespace():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'v.strip().replace("Z", "+00:00")' in workflow


def test_pc_off_workflow_reports_safe_heartbeat_time_range():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "EVIDENCE_HEARTBEAT_MIN_UTC=" in workflow
    assert "EVIDENCE_HEARTBEAT_MAX_UTC=" in workflow

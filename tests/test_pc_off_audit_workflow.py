from pathlib import Path


WORKFLOW = Path(".github/workflows/audit-futures-pc-off.yml")


def test_pc_off_workflow_uses_tested_heartbeat_parser_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "extract_futures_heartbeat_payloads(evidence_file)" in workflow
    assert "re.search(" not in workflow
    assert "json.loads(" not in workflow


def test_pc_off_embedded_python_compiles():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = "python - <<'PY'\n"
    script = workflow.split(marker, 1)[1].split("\n          PY", 1)[0]
    script = "\n".join(line[10:] if line.startswith("          ") else line for line in script.splitlines())
    script = script.replace("${{ github.run_id }}", "12345")
    compile(script, str(WORKFLOW), "exec")

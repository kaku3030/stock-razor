"""Unknown failures must be retained without raw logs or speculative diagnoses."""
import json

import pytest

from engineering_autonomy.incident_memory import (
    IncidentMemoryError, observe_failure, summary,
)

SHA1 = "a" * 40
SHA2 = "b" * 40
QUEUE = "c" * 64


def receipt(tmp_path, **overrides):
    args = dict(task_id="quality-check", kind="quality-check", exit_code=7,
                queue_sha=QUEUE, source_sha=SHA1, environment="github-actions",
                run_id="3924")
    args.update(overrides)
    return observe_failure(tmp_path / "incidents.json", **args)


def test_new_failure_is_unknown_not_a_guessed_fix(tmp_path):
    first = receipt(tmp_path)
    assert first["action"] == "INVESTIGATE_ONCE"
    assert first["diagnosis"] == "UNKNOWN_PENDING_ROOT_CAUSE"
    assert first["evidence"] == "LOCAL_RECEIPT_ONLY_CLOUD_SYNC_NOT_VERIFIED"
    record = json.loads((tmp_path / "incidents.json").read_text())["records"][0]
    assert record["resolution"] == "UNVERIFIED"
    assert record["first_run_id"] == "3924"
    assert record["source_sha"] == SHA1


def test_identical_sha_and_environment_dedupe(tmp_path):
    a = receipt(tmp_path)
    b = receipt(tmp_path, run_id="3925")
    assert b["action"] == "STOP_DUPLICATE"
    assert b["fingerprint"] == a["fingerprint"]
    assert summary(tmp_path / "incidents.json")["records"][0]["observations"] == 2
    assert summary(tmp_path / "incidents.json")["count"] == 1


def test_changed_sha_or_environment_is_new_proof_scope(tmp_path):
    receipt(tmp_path)
    assert receipt(tmp_path, source_sha=SHA2)["action"] == "INVESTIGATE_ONCE"
    assert receipt(tmp_path, environment="windows-local")["action"] == "INVESTIGATE_ONCE"
    assert summary(tmp_path / "incidents.json")["count"] == 3


def test_distinct_exit_code_distinct_error_family(tmp_path):
    a = receipt(tmp_path)
    b = receipt(tmp_path, exit_code=8)
    assert a["fingerprint"] != b["fingerprint"]
    assert summary(tmp_path / "incidents.json")["count"] == 2


@pytest.mark.parametrize("params", [
    {"task_id": "token=1234 foo"},
    {"environment": "unknown;cat ~/.aws/credentials"},
    {"run_id": "https://bad.example"},
    {"queue_sha": "main"},
    {"source_sha": "not-a-sha"},
    {"exit_code": True},
])
def test_malformed_identifiers_rejected_before_persistence(tmp_path, params):
    with pytest.raises(IncidentMemoryError):
        receipt(tmp_path, **params)
    assert not (tmp_path / "incidents.json").exists()


def test_invalid_existing_ledger_refuses_mutation(tmp_path):
    p = tmp_path / "incidents.json"
    p.write_text('{"schema":"wrong","records":[]}', encoding="utf-8")
    with pytest.raises(IncidentMemoryError, match="SCHEMA"):
        receipt(tmp_path)
    assert json.loads(p.read_text())["schema"] == "wrong"


def test_cli_uses_redacted_structured_fields_only(tmp_path):
    receipt(tmp_path)
    content = (tmp_path / "incidents.json").read_text(encoding="utf-8")
    for dangerous in ("Traceback", "API_KEY", "password", "token=", "Authorization"):
        assert dangerous not in content
    brief = summary(tmp_path / "incidents.json")
    assert len(json.dumps(brief)) < 650
    assert brief["records"][0]["fingerprint"]


def test_no_raw_error_or_traceback_arguments_in_interface(tmp_path):
    with pytest.raises(TypeError):
        observe_failure(tmp_path / "incidents.json", task_id="quality-check",
                        kind="quality-check", exit_code=1, queue_sha=QUEUE,
                        traceback="secret")

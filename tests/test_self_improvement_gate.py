"""Project-wide self-improvement registry and reproducible duplicate-retry checks."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "self_improvement_gate", ROOT / "scripts" / "self_improvement_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)
SHA = "a" * 40
OTHER_SHA = "b" * 40


def test_registry_canonical_and_complete():
    registry = gate.load_registry()
    assert registry["schema"] == gate.SCHEMA
    assert len(registry["records"]) >= 10
    assert any(x["id"] == "US-001" for x in registry["records"])
    assert any(x["id"] == "ENG-003" for x in registry["records"])


def test_same_known_failure_and_exact_sha_stops_retry():
    item = gate.classify(gate.load_registry(), signature="S1_60M_NORMALIZE ROW_COUNT_BELOW_MIN",
                         sha=SHA, previous_sha=SHA)
    assert item["action"] == "STOP_DUPLICATE"
    assert item["failure_ids"] == ["CN-001"]
    assert "same" in item["reason"].lower()
    assert item["mandatory_actions"]


def test_different_sha_requires_diagnosis_not_success():
    item = gate.classify(gate.load_registry(), signature="UNSUPPORTED_TIMEFRAME 1D",
                         sha=SHA, previous_sha=OTHER_SHA)
    assert item["action"] == "DIAGNOSE_OR_PATCH"
    assert item["failure_ids"] == ["US-001"]


def test_unknown_signature_never_claims_pass():
    item = gate.classify(gate.load_registry(), signature="MYSTERY_NEW_UNSEEN_DEFECT",
                         sha=SHA, previous_sha=SHA)
    assert item == {"action": "UNKNOWN", "failure_ids": [],
                    "reason": "NO_EXACT_REGISTERED_FAILURE_MATCH", "source_sha": SHA}


def test_partial_signature_does_not_falsely_match():
    item = gate.classify(gate.load_registry(), signature="S1_60M_NORMALIZE only",
                         sha=SHA, previous_sha=SHA)
    assert item["action"] == "UNKNOWN"


def test_invalid_revision_fails_closed():
    with pytest.raises(gate.RegistryError, match="REVISION_SHA_INVALID"):
        gate.classify(gate.load_registry(), signature="ROW_COUNT_BELOW_MIN S1_60M_NORMALIZE",
                      sha="main", previous_sha=SHA)


def test_duplicate_failure_id_rejected(tmp_path):
    registry = copy.deepcopy(gate.load_registry())
    registry["records"].append(copy.deepcopy(registry["records"][0]))
    dest = tmp_path / "dupe.json"
    dest.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(gate.RegistryError, match="DUPLICATE"):
        gate.load_registry(dest)


def test_absent_regression_file_rejected(tmp_path):
    registry = copy.deepcopy(gate.load_registry())
    registry["records"][0]["regression_evidence"] = "tests/does_not_exist_anywhere.py"
    dest = tmp_path / "missing.json"
    dest.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(gate.RegistryError, match="REGISTRY_TEST_NOT_FOUND"):
        gate.load_registry(dest)


def test_untrusted_non_github_evidence_rejected(tmp_path):
    registry = copy.deepcopy(gate.load_registry())
    registry["records"][0]["evidence_url"] = "https://bad.invalid/fake"
    dest = tmp_path / "untrusted.json"
    dest.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(gate.RegistryError, match="REGISTRY_EVIDENCE_INVALID"):
        gate.load_registry(dest)


def test_cli_stop_duplicate_exit_code(capsys):
    status = gate.main(["--signature", "UNSUPPORTED_TIMEFRAME 1D",
                        "--sha", SHA, "--previous-sha", SHA])
    assert status == 3
    result = json.loads(capsys.readouterr().out)
    assert result["action"] == "STOP_DUPLICATE"


def test_cli_registry_check_and_status(capsys):
    assert gate.main(["--check-registry"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    assert gate.main(["--status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert any(x["id"] == "CN-002" for x in status["records"])

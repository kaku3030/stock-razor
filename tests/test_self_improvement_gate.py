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


def test_vendor_ticker_and_endpoint_dot_signatures_are_valid():
    registry = gate.load_registry()
    ticker = gate.classify(registry, signature="Tencent fallback observed for 518880.SH",
                           sha=SHA, previous_sha=SHA)
    assert ticker["action"] == "STOP_DUPLICATE"
    assert ticker["failure_ids"] == ["CN-002"]
    endpoint = gate.classify(registry, signature="KLINES.GET wrongly used INTRADAY",
                             sha=SHA, previous_sha=SHA)
    assert endpoint["failure_ids"] == ["CN-003"]


def test_cannot_claim_resolved_without_regression(tmp_path):
    registry = copy.deepcopy(gate.load_registry())
    registry["records"][0]["status"] = "RESOLVED"
    registry["records"][0]["regression_evidence"] = "NOT_VERIFIED"
    dest = tmp_path / "unproven.json"
    dest.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(gate.RegistryError, match="RESOLVED_WITHOUT_REGRESSION"):
        gate.load_registry(dest)


def test_brief_is_bounded_and_does_not_claim_cross_chat_delivery(capsys):
    assert gate.main(["--brief"]) == 0
    packet = json.loads(capsys.readouterr().out)
    assert packet["schema"] == gate.SCHEMA
    assert packet["count"] >= 13
    assert packet["duplicate_retry_policy"] == "STOP_ON_SAME_SHA_AND_NO_NEW_EVIDENCE"
    assert packet["cross_chat_delivery"] == "NOT_VERIFIED"
    assert "US-002" in packet["p0"]
    assert len(json.dumps(packet)) < 900


@pytest.mark.parametrize("file_name,next_step", [
    ("engineering-autonomy-120m.yml", "Install pinned test dependencies"),
    ("engineering-autonomy-coding-v1-1.yml", "Validate trusted one-shot task"),
])
def test_engineering_workflows_run_fast_gate_before_tasks(file_name, next_step):
    workflow = (ROOT / ".github" / "workflows" / file_name).read_text(encoding="utf-8")
    first = workflow.index("name: Fast shared self-improvement gate")
    assert first < workflow.index(next_step)
    guard = workflow[first:workflow.index(next_step)]
    assert "git ls-remote origin refs/heads/main" in guard
    assert 'test "$remote_main" = "$GITHUB_SHA"' in guard
    assert "python scripts/self_improvement_gate.py --check-registry" in guard
    assert "python scripts/self_improvement_gate.py --brief" in guard
    assert "AUTONOMY_MAIN_MOVED_OR_UNKNOWN" in guard


def test_cn_004_live_1m_drift_audit_fix_is_mitigated():
    registry = gate.load_registry()
    item = next(row for row in registry["records"] if row["id"] == "CN-004")
    assert item["status"] == "MITIGATED"
    assert item["regression_evidence"] == "tests/test_tickflow_windows_readonly_audit.py"

import pytest

from scripts.e06_benchmark import LAYERS, PROTECTED_CONTRACTS, make_row, validate_row


def test_row_keeps_three_layers_and_pending_fresh_context():
    row = make_row(task_id="T1", run_id="smoke", context="current-chat")
    validate_row(row)
    assert tuple(row["layers"]) == LAYERS
    assert row["official_status"] == "CONTAMINATED"
    assert row["contamination"] is True


def test_contaminated_row_cannot_pass():
    row = make_row(task_id="T5", run_id="bad", context="current-chat")
    row["correctness_gate"]["result"] = "PASS"
    with pytest.raises(ValueError, match="contaminated"):
        validate_row(row)


def _fresh_with_gate(values):
    row = make_row(task_id="T1", run_id="x", context="fresh", contamination=False)
    row["correctness_gate"] = {"result": "PASS", "protected_governance": values}
    return row


def test_missing_protected_contract_is_not_pass():
    values = {name: "PASS" for name in PROTECTED_CONTRACTS[:-1]}
    with pytest.raises(ValueError, match="seven"):
        validate_row(_fresh_with_gate(values))


@pytest.mark.parametrize("bad", ["FAIL", "UNKNOWN", None])
def test_non_passing_protected_contract_is_not_pass(bad):
    values = {name: "PASS" for name in PROTECTED_CONTRACTS}
    values[PROTECTED_CONTRACTS[0]] = bad
    with pytest.raises(ValueError, match="seven"):
        validate_row(_fresh_with_gate(values))


def test_all_explicit_protected_contracts_pass():
    row = _fresh_with_gate({name: "PASS" for name in PROTECTED_CONTRACTS})
    validate_row(row)
    assert row["official_status"] == "PENDING_FRESH_CONTEXT"


def test_fresh_sample_can_be_eligible_only_after_correctness():
    row = make_row(task_id="T1", run_id="x", context="fresh", contamination=False)
    row["official_status"] = "ELIGIBLE"
    with pytest.raises(ValueError, match="external-only"):
        validate_row(row)


def test_current_chat_cannot_be_promoted_by_toggling_fields():
    row = make_row(task_id="T1", run_id="x", context="current-chat")
    row["contamination"] = False
    row["official_status"] = "ELIGIBLE"
    row["correctness_gate"] = {
        "result": "PASS",
        "protected_governance": {name: "PASS" for name in PROTECTED_CONTRACTS},
    }
    with pytest.raises(ValueError, match="external-only"):
        validate_row(row)


def test_unknown_metric_is_rejected():
    with pytest.raises(ValueError, match="unknown metrics"):
        make_row(task_id="T1", run_id="x", context="fresh", typo_metric=1)


def test_current_chat_full_row_forgery_cannot_become_official_locally():
    row = make_row(task_id="T1", run_id="x", context="current-chat")
    row.update({"context": "fresh", "contamination": False, "official_status": "ELIGIBLE",
                "fresh_context_identity": "fresh-context-v0.1",
                "fresh_context_transition": {"validated": True, "source": "fresh-context"},
                "fresh_context_proof": "looks-valid"})
    row["correctness_gate"] = {"result": "PASS", "protected_governance": {name: "PASS" for name in PROTECTED_CONTRACTS}}
    with pytest.raises(ValueError, match="external-only"):
        validate_row(row)


def test_fresh_all_pass_cannot_become_official_locally():
    row = _fresh_with_gate({name: "PASS" for name in PROTECTED_CONTRACTS})
    row["official_status"] = "ELIGIBLE"
    with pytest.raises(ValueError, match="external-only"):
        validate_row(row)


def test_contaminated_origin_cannot_be_marked_pending_fresh_context():
    row = make_row(task_id="T1", run_id="x", context="current-chat")
    row.update({"context": "fresh", "contamination": True, "official_status": "PENDING_FRESH_CONTEXT"})
    row["correctness_gate"] = {"result": "PENDING", "protected_governance": []}
    with pytest.raises(ValueError, match="contaminated"):
        validate_row(row)

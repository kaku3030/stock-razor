"""Context Manager never promotes a CI failure or PR-head CI to main acceptance."""
import pytest
from src.services.context_manager import ContextManagerStore


@pytest.mark.parametrize("result", ["failure", "cancelled", "timed_out", "action_required", "neutral", "skipped"])
def test_non_success_ci_fails_closed(tmp_path, result):
    store = ContextManagerStore(tmp_path / "state.json")
    store.record(event_id="ci:123", event_type="ci_" + result, source="ci",
                 payload={"branch": "feature", "conclusion": result})
    state = store.read()
    assert state["status"] == "BLOCKED"
    assert state["domains"]["ci"]["status"] == "BLOCKED"
    assert state["domains"]["ci"]["scope"] == "PR_HEAD"
    assert state["domains"]["ci"]["main_ci_qualification"] == "UNVERIFIED"
    assert state["safety"]["live_trade"] is False


def test_pr_head_success_stays_unverified_for_main(tmp_path):
    store = ContextManagerStore(tmp_path / "state.json")
    store.record(event_id="ci:ok", event_type="ci_success", source="ci",
                 payload={"branch": "feature", "conclusion": "success"})
    ci = store.read()["domains"]["ci"]
    assert ci["status"] == "ACTIVE"
    assert ci["scope"] == "PR_HEAD"
    assert ci["main_ci_qualification"] == "UNVERIFIED"


def test_deployment_alignment_relative_only_to_recorded_merge(tmp_path):
    store = ContextManagerStore(tmp_path / "state.json")
    store.record(event_id="deploy:1", event_type="deployment_passed",
                 source="deployment", payload={"repo_sha": "aaa"})
    assert store.read()["domains"]["deploy"]["latest_recorded_pr_sha_match"] == "UNKNOWN"
    store.record(event_id="pr:2", event_type="pr_merged",
                 source="engineering", payload={"merge_sha": "bbb"})
    assert store.read()["domains"]["deploy"]["latest_recorded_pr_sha_match"] == "MISMATCH"
    store.record(event_id="deploy:2", event_type="deployment_passed",
                 source="deployment", payload={"repo_sha": "bbb"})
    assert store.read()["domains"]["deploy"]["latest_recorded_pr_sha_match"] == "MATCH"

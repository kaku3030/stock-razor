"""Run the real embedded AWS verification segment with synthetic heartbeat.

No AWS, SSM, moomoo/OpenD, quote context, network, account, or trading calls.
"""
from copy import deepcopy
from pathlib import Path

import pytest


VERIFY_PATH = Path("ops/aws/verify_us_opend_livefeed.sh")
WF_PATH = Path(".github/workflows/deploy-us-opend-livefeed.yml")

SCOPE = "EXISTING_BRIDGE_ACK_ONLY_NOT_PROVIDER_RECONCILIATION"


def _segment():
    source = VERIFY_PATH.read_text(encoding="utf-8")
    start = source.index("# Runtime dynamic candidate observation is intentionally read-only.")
    end = source.index("\nfor symbol, item in warm_symbols.items():", start)
    snippet = source[start:end]
    compile(snippet, str(VERIFY_PATH) + ":candidate-acceptance", "exec")
    return snippet


def _payload(status="NO_CHANGE_PLAN", additions=None):
    if additions is None:
        additions = []
    return {
        "symbols": ["US.AMD", "US.NVDA"],
        "subscribed": ["US.AMD", "US.NVDA"],
        "dynamic_subscription_preview": {
            "status": status,
            "reason": (
                "DRY_RUN_NEVER_MUTATES" if status == "NO_CHANGE_PLAN"
                else "FRESH_PROVIDER_QUOTA_NOT_VERIFIED"
            ),
            "acknowledged_count": 2,
            "proposed_additions": list(additions),
            "proposed_removals": [],
            "evidence_scope": SCOPE,
            "provider_calls": 0,
            "subscription_changes": 0,
            "radar_admission": "BLOCKED",
            "source_arbiter_admission": "BLOCKED",
            "paper_auto_ready": False,
            "live_trade": False,
        },
    }


def _accept(heartbeat):
    scope = {
        "heartbeat": heartbeat,
        "expected_symbols": set(heartbeat["symbols"]),
    }
    exec(_segment(), scope)


def test_existing_fixed_pool_with_no_deltas_is_observer_readonly_accepted():
    _accept(_payload())


def test_optional_candidate_additions_must_stay_blocked_without_quota():
    _accept(_payload(status="BLOCKED", additions=["US.CIEN"]))


@pytest.mark.parametrize(
    "change",
    [
        ("status", "PLAN_ONLY"),
        ("reason", "OBSERVER_EXCEPTION"),
        ("provider_calls", 1),
        ("provider_calls", False),
        ("subscription_changes", 2),
        ("evidence_scope", "PROVIDER_RECONCILED"),
        ("radar_admission", "ENABLED"),
        ("source_arbiter_admission", "ENABLED"),
        ("paper_auto_ready", True),
        ("live_trade", True),
        ("acknowledged_count", 1),
        ("proposed_removals", ["US.AMD"]),
    ],
)
def test_unqualified_or_mutating_candidate_preview_fails_deployment(change):
    key, value = change
    doc = _payload()
    doc["dynamic_subscription_preview"][key] = value
    with pytest.raises(AssertionError):
        _accept(doc)


def test_missing_observer_and_unknown_reason_do_not_count_as_deployed():
    doc = _payload()
    del doc["dynamic_subscription_preview"]
    with pytest.raises(AssertionError):
        _accept(doc)
    doc = _payload("BLOCKED", ["US.CIEN"])
    doc["dynamic_subscription_preview"]["reason"] = "OBSERVER_EXCEPTION"
    with pytest.raises(AssertionError):
        _accept(doc)


def test_duplicate_mismatched_or_absent_owner_acknowledgment_fails():
    for ack in ([], ["US.AMD"], ["US.AMD", "US.AMD"], None):
        doc = _payload()
        doc["subscribed"] = ack
        with pytest.raises(AssertionError):
            _accept(doc)


def test_blocked_additions_without_candidates_are_not_qualified():
    doc = _payload(status="BLOCKED", additions=[])
    with pytest.raises(AssertionError):
        _accept(doc)


def test_added_candidate_cannot_claim_real_subscription_success():
    doc = _payload(status="NO_CHANGE_PLAN", additions=["US.CIEN"])
    with pytest.raises(AssertionError):
        _accept(doc)


def test_workflow_requires_safe_observer_marker_without_raw_cloud_logs():
    wf = WF_PATH.read_text(encoding="utf-8")
    verifier = VERIFY_PATH.read_text(encoding="utf-8")
    assert 'echo "OPEND_CANDIDATE_PREVIEW=READONLY_PASS"' in verifier
    assert wf.count("OPEND_CANDIDATE_PREVIEW=READONLY_PASS") >= 4
    assert 'grep -Fx OPEND_CANDIDATE_PREVIEW=READONLY_PASS' in wf
    assert "cat \"$status\"" not in wf
    assert 'echo "$out"' not in wf
    assert 'printf \'%s\\n\' "$inv"' not in wf
    assert "inputs.approve_restart == true" in wf
    assert "inputs.expected_main_sha == github.sha" in wf

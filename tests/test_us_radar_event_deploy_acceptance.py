"""Run the real deployment verifier against blocked research-inbox evidence."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SHA = "a" * 40
REASON = "BAR_EVENT_SOURCE_NOT_QUALIFIED"


def payload():
    return {
        "type": "us_radar_research_heartbeat", "worker_repo_sha": SHA,
        "expected_source_repo_sha": SHA, "sequence": 1,
        "research_only": True, "can_confirm_signal": False,
        "radar_admission": "BLOCKED", "live_trade": False,
        "bar_event_queue": {name: 0 for name in (
            "event_pending", "event_claimed", "event_acknowledged", "event_dead_letter",
            "ai_started", "ai_succeeded", "ai_unknown", "ai_expired")},
        "radar_analysis_performed": False, "radar_analysis_latency_ms": None,
        "data_to_radar_latency_ms": None,
        "daily_history": {"status": "PASS", "historical_query": True,
            "currentness_proven": False, "bar_closure_promotion_authorized": False,
            "research_only": True, "can_confirm_signal": False,
            "radar_admission": "BLOCKED", "live_trade": False,
            "symbols": {"US.AMD": {"row_count": 120, "latest_date": "2026-10-16"}}},
        "evaluation": {"status": "BLOCKED", "reasons": [REASON],
            "source_repo_sha": SHA, "source_delivery_mode": "REALTIME",
            "source_bar_closure": "UNPROVEN", "source_radar_admission": "BLOCKED",
            "source_live_trade": False, "research_only": True, "can_confirm_signal": False,
            "bar_event_ingress": {"status": "BLOCKED", "created_count": 0,
                "duplicate_count": 0, "reasons": [REASON]},
            "admission_diagnostics": {"decision": "BLOCKED", "promotion_authorized": False,
                "source_radar_admission": "BLOCKED", "source_live_trade": False,
                "delivery_mode_realtime": True, "bar_closure_proven": False,
                "minimum_source_prerequisites_met": False, "reasons": ["PROMOTION_NOT_AUTHORIZED"]}},
    }


@pytest.mark.parametrize("case,passes", [
    ("blocked_zero_events", True), ("legacy_stale", True),
    ("events_disabled", False), ("source_mismatch", False),
    ("events_created", False), ("queue_corrupt", False),
    ("unexpected_reason", False), ("false_block_for_qualified_source", False),
    ("unsafe_flag", False), ("missing_ingress", False),
])
def test_real_verifier_preserves_data_and_safety_gates(tmp_path, case, passes):
    data = copy.deepcopy(payload())
    evaluation = data["evaluation"]
    enabled = "true"
    if case == "legacy_stale":
        evaluation["reasons"] = ["SOURCE_EXPORT_STALE"]
        evaluation.pop("bar_event_ingress")
    elif case == "events_disabled":
        enabled = "false"
        data["bar_event_queue"] = None
    elif case == "source_mismatch":
        evaluation["source_repo_sha"] = "b" * 40
    elif case == "events_created":
        evaluation["bar_event_ingress"]["created_count"] = 1
    elif case == "queue_corrupt":
        data["bar_event_queue"]["ai_started"] = True
    elif case == "unexpected_reason":
        evaluation["reasons"].append("SOURCE_INVALID")
    elif case == "false_block_for_qualified_source":
        evaluation["source_bar_closure"] = "PROVEN"
        evaluation["admission_diagnostics"].update(bar_closure_proven=True, minimum_source_prerequisites_met=True)
    elif case == "unsafe_flag":
        data["live_trade"] = True
    elif case == "missing_ingress":
        evaluation.pop("bar_event_ingress")
    status = tmp_path / "heartbeat.json"
    status.write_text(json.dumps(data))
    script = Path("ops/aws/verify_us_radar_worker.sh").read_text().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    result = subprocess.run([sys.executable, "-", str(status), SHA, SHA], input=script,
        env={**os.environ, "CLOSED_BAR_EVENTS_ENABLED": enabled}, text=True,
        capture_output=True, timeout=5)
    assert (result.returncode == 0) is passes, result.stderr

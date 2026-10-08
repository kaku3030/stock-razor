from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from scripts.audit_cloud_runtime_readonly import (
    _COMPONENTS,
    audit_twice,
    component_snapshot,
)

NOW = datetime(2026, 10, 8, 6, 30, tzinfo=timezone.utc)


def payload_for(name, *, seq=5, emitted=None, **changes):
    _, _, kind_field, kind_value = _COMPONENTS[name]
    payload = {
        kind_field: kind_value,
        "emitted_at_utc": (emitted or NOW - timedelta(seconds=2)).isoformat(),
        "sequence": seq,
        "repo_sha": "a" * 40,
        "worker_repo_sha": "b" * 40,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "status": "PASS",
        "poll_status": "PASS",
        "radar_analysis_performed": True,
        "radar_analysis_latency_ms": 28.5,
        "data_to_radar_latency_ms": 140.0,
        "failure_reason": "SECRET_NEVER_PRINT",
        "api_key": "SECRET_NEVER_PRINT",
    }
    payload.update(changes)
    return payload


def probe(name, payload, active=True):
    return component_snapshot(
        name,
        now=NOW,
        check_unit=lambda unit: active,
        read_json=lambda path: payload,
    )


@pytest.mark.parametrize("name", sorted(_COMPONENTS))
def test_current_research_component_is_operational_only(name):
    result = probe(name, payload_for(name))
    assert result["operational_state"] == "HEARTBEAT_CURRENT"
    assert result["heartbeat_age_seconds"] == 2
    assert result["sequence"] == 5
    assert result["safety_evidence"] == "COMPLETE"
    assert "SECRET_NEVER_PRINT" not in json.dumps(result)
    if name.endswith("_radar"):
        assert result["radar_analysis_latency_ms"] == 28.5
    else:
        assert result["radar_analysis_latency_ms"] is None


def test_legacy_us_livefeed_missing_research_keys_is_explicit_unknown():
    source = payload_for("us_livefeed")
    source.pop("research_only")
    source.pop("can_confirm_signal")
    result = probe("us_livefeed", source)
    assert result["operational_state"] == "HEARTBEAT_CURRENT"
    assert result["safety_evidence"] == "INCOMPLETE"
    assert result["research_only"] is None


@pytest.mark.parametrize("bad", [
    {"live_trade": True},
    {"radar_admission": "ADMITTED"},
    {"can_confirm_signal": True},
    {"research_only": False},
])
def test_any_unsafe_governance_fails_closed(bad):
    result = probe("cn_observer", payload_for("cn_observer", **bad))
    assert result["operational_state"] == "SAFETY_CONTRACT_INVALID"
    assert result["safety_evidence"] == "INVALID"


def test_missing_or_malformed_json_does_not_manufacture_heartbeat():
    result = probe("cn_radar", None)
    assert result["operational_state"] == "HEARTBEAT_UNAVAILABLE"
    assert result["sequence"] is None


def test_schema_mismatch_blocks_heartbeat():
    result = probe("us_radar", payload_for("us_radar", type="wrong"))
    assert result["operational_state"] == "SCHEMA_MISMATCH"


def test_stale_and_inactive_are_separately_reported():
    stale = probe(
        "cn_observer",
        payload_for("cn_observer", emitted=NOW - timedelta(minutes=7)),
    )
    inactive = probe("cn_observer", payload_for("cn_observer"), active=False)
    assert stale["operational_state"] == "HEARTBEAT_STALE"
    assert inactive["operational_state"] == "UNIT_INACTIVE"


def test_future_source_timestamp_is_not_fake_zero_latency():
    result = probe(
        "us_livefeed",
        payload_for("us_livefeed", emitted=NOW + timedelta(seconds=2)),
    )
    assert result["operational_state"] == "CLOCK_REVERSAL"
    assert result["heartbeat_age_seconds"] is None


def test_missing_or_boolean_sequence_stays_unknown():
    result = probe("cn_radar", payload_for("cn_radar", sequence=True))
    assert result["operational_state"] == "SEQUENCE_UNKNOWN"


def test_two_samples_show_progress_without_off_pc_promotion():
    seen = {name: 0 for name in _COMPONENTS}

    def read(path):
        name = next(k for k, v in _COMPONENTS.items() if v[1] == path)
        seen[name] += 1
        return payload_for(name, seq=seen[name])

    result = audit_twice(
        interval_seconds=0,
        check_unit=lambda unit: True,
        read_json=read,
        clock=lambda: NOW,
        sleeper=lambda _: pytest.fail("should not sleep"),
    )
    assert result["audit_status"] == "COMPLETE"
    assert result["all_components_current"] is True
    assert result["all_safety_evidence_complete"] is True
    assert all(result["heartbeat_progress_observed"].values())
    assert result["off_pc_independent_acquisition"] == "NOT_VERIFIED"
    assert result["intraday_data_quality"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] == "NO"
    assert result["can_confirm_signal"] is False
    assert result["external_notifications_sent"] == 0
    assert "SECRET_NEVER_PRINT" not in json.dumps(result)


def test_empty_runtime_evidence_is_reported_as_gaps():
    result = audit_twice(
        interval_seconds=0,
        read_json=lambda path: None,
        check_unit=lambda unit: False,
        clock=lambda: NOW,
    )
    assert result["audit_status"] == "COMPLETE_WITH_GAPS"
    assert result["all_components_current"] is False
    assert not any(result["heartbeat_progress_observed"].values())


def test_interval_out_of_bounds_rejected():
    with pytest.raises(ValueError):
        audit_twice(interval_seconds=-1)
    with pytest.raises(ValueError):
        audit_twice(interval_seconds=61)


def test_ssm_workflow_is_read_only_and_uses_pinned_main():
    source = Path(".github/workflows/audit-cloud-independent-runtime.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in source
    assert "aws-actions/configure-aws-credentials@v4" in source
    assert "ssm send-command" in source
    assert "AWS-RunShellScript" in source
    assert 'script_sha="$(git rev-parse HEAD)"' in source
    assert "scripts/audit_cloud_runtime_readonly.py" in source
    assert "RADAR_ADMISSION=BLOCKED" in source
    assert "LIVE_TRADE=NO" in source
    assert "systemctl restart" not in source
    assert "systemctl stop" not in source
    assert "pip install" not in source

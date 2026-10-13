"""Offline, synthetic, no AWS/provider/broker/network tests."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from data_provider.cloud_ops_readonly_status import _project, read_cloud_ops_status
from scripts.audit_cloud_runtime_readonly import _COMPONENTS

NOW = datetime(2026, 10, 13, 6, 0, tzinfo=timezone.utc)


def make_data(name, **updates):
    _, _, field, expected = _COMPONENTS[name]
    obj = {
        field: expected, "emitted_at_utc": (NOW - timedelta(seconds=2)).isoformat(),
        "sequence": 42, "repo_sha": "a" * 40,
        "research_only": True, "can_confirm_signal": False,
        "radar_admission": "BLOCKED", "live_trade": False,
        "status": "PASS", "api_key": "DO_NOT_RETURN_SECRET",
        "failure_reason": "DO_NOT_RETURN_SECRET",
    }
    obj.update(updates)
    return obj


def fixture(overrides=None, *, active=True):
    overrides = overrides or {}
    path_to_name = {v[1]: k for k, v in _COMPONENTS.items()}
    payloads = {k: make_data(k, **overrides.get(k, {})) for k in _COMPONENTS}
    return read_cloud_ops_status(
        now_utc=NOW, check_unit=lambda unit: active,
        read_json=lambda path: payloads[path_to_name[path]],
    )


def test_complete_cached_health_is_not_aws_authority():
    result = fixture()
    assert result["ok"] is True
    assert result["status"] == "OPERATIONAL_OBSERVATION_ONLY"
    assert set(result["components"]) == set(_COMPONENTS)
    assert result["mutation_allowed"] is False
    assert result["aws_api_requests"] == result["provider_requests"] == 0
    assert result["live_trade"] is False
    assert result["source_arbiter_admission"] == result["radar_admission"] == "BLOCKED"
    assert result["off_pc_independent_acquisition"] == "NOT_VERIFIED"
    assert "DO_NOT_RETURN_SECRET" not in json.dumps(result)


def test_unsafe_heartbeat_blocks_without_secret_leak():
    result = fixture({"cn_observer": {"radar_admission": "PASS"}})
    assert result["ok"] is False
    assert result["status"] == "BLOCKED"
    assert result["components"]["cn_observer"]["operational_state"] == "SAFETY_CONTRACT_INVALID"
    assert result["radar_admission"] == "BLOCKED"


def test_inactive_or_stale_unit_never_means_operational():
    assert fixture(active=False)["status"] == "BLOCKED"
    result = fixture({"us_radar": {"emitted_at_utc": (NOW-timedelta(minutes=8)).isoformat()}})
    assert result["ok"] is False
    assert result["components"]["us_radar"]["operational_state"] == "HEARTBEAT_STALE"


def test_naive_clock_and_reader_errors_fail_closed():
    assert read_cloud_ops_status(now_utc=datetime(2026, 10, 13))["status"] == "INVALID_CLOCK"
    result = read_cloud_ops_status(
        now_utc=NOW, check_unit=lambda unit: True,
        read_json=lambda path: (_ for _ in ()).throw(OSError("DO_NOT_RETURN_SECRET")),
    )
    assert result["ok"] is False
    assert "DO_NOT_RETURN_SECRET" not in json.dumps(result)


def test_mcp_source_and_installer_pin_readonly_tool():
    mcp = Path("realtime_monitor/readonly_mcp_server.py").read_text(encoding="utf-8")
    installer = Path("ops/aws/install_readonly_mcp.sh").read_text(encoding="utf-8")
    assert "def get_cloud_ops_status() -> dict:" in mcp
    assert "return read_cloud_ops_status()" in mcp
    assert "get_cloud_ops_status" in installer
    assert 'assert result["live_trade"] is False' in installer
    assert 'assert result["radar_admission"] == "BLOCKED"' in installer


def test_mcp_projection_rejects_unsanitized_unexpected_values():
    result = _project({
        "operational_state": "SECRET_STATUS", "unit_active": 1,
        "heartbeat_age_seconds": float("inf"), "sequence": True,
        "repo_sha": "INVALID_SECRET", "sample_status": "SECRET_STATUS",
        "safety_evidence": "WRONG", "api_key": "DO_NOT_RETURN_SECRET",
    })
    assert result["operational_state"] == "UNKNOWN"
    assert result["safety_evidence"] == "UNKNOWN"
    assert result["unit_active"] is False
    assert result["heartbeat_age_seconds"] is None
    assert result["sequence"] is None
    assert result["repo_sha"] is None
    assert "DO_NOT_RETURN_SECRET" not in json.dumps(result)

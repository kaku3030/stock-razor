"""Bounded EC2-local operational health for the existing read-only MCP.

This is not an AWS management API, IAM proof, or authority to execute SSM.
Only fixed systemd units and cached heartbeats are consulted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from re import fullmatch
from typing import Callable

from scripts.audit_cloud_runtime_readonly import component_snapshot

_COMPONENTS = ("us_livefeed", "us_radar", "cn_observer", "cn_radar")
_STATES = frozenset({
    "UNKNOWN", "HEARTBEAT_UNAVAILABLE", "SCHEMA_MISMATCH",
    "SAFETY_CONTRACT_INVALID", "TIMESTAMP_INVALID", "CLOCK_REVERSAL",
    "UNIT_INACTIVE", "HEARTBEAT_STALE", "SEQUENCE_UNKNOWN", "HEARTBEAT_CURRENT",
})
_SAMPLE_STATES = frozenset({"PASS", "STALE", "DEGRADED", "BLOCKED", "UNKNOWN", "UNCHANGED"})
_SAFETY_STATES = frozenset({"COMPLETE", "INCOMPLETE", "INVALID", "UNKNOWN"})


def _project(raw: object) -> dict:
    """Strict output allowlist, even if upstream audit adds diagnostic fields."""
    value = raw if isinstance(raw, dict) else {}
    state = value.get("operational_state")
    safety = value.get("safety_evidence")
    sample = value.get("sample_status")
    age = value.get("heartbeat_age_seconds")
    seq = value.get("sequence")
    sha = value.get("repo_sha")
    return {
        "operational_state": state if type(state) is str and state in _STATES else "UNKNOWN",
        "unit_active": value.get("unit_active") is True,
        "heartbeat_age_seconds": round(age, 3) if type(age) in (int, float) and isfinite(age) and 0 <= age <= 86400 else None,
        "sequence": seq if type(seq) is int and 0 <= seq <= 2**63 - 1 else None,
        "repo_sha": sha if type(sha) is str and fullmatch(r"[a-f0-9]{40}", sha) else None,
        "sample_status": sample if type(sample) is str and sample in _SAMPLE_STATES else None,
        "safety_evidence": safety if type(safety) is str and safety in _SAFETY_STATES else "UNKNOWN",
    }


def read_cloud_ops_status(
    *,
    now_utc: datetime | None = None,
    check_unit: Callable[[str], bool] | None = None,
    read_json: Callable[[str], dict | None] | None = None,
) -> dict:
    """Read fixed EC2 systemd/cache status; no AWS API, provider or mutating I/O."""
    now = now_utc or datetime.now(timezone.utc)
    base = {
        "schema": "stock_razor_cloud_ops_readonly_v0_1",
        "measurement_scope": "EC2_LOCAL_SYSTEMD_AND_HEARTBEAT_ONLY",
        "read_only": True,
        "mutation_allowed": False,
        "aws_api_requests": 0,
        "provider_requests": 0,
        "off_pc_independent_acquisition": "NOT_VERIFIED",
        "data_currentness_proven": False,
        "can_confirm_signal": False,
        "research_only": True,
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "paper_auto_ready": False,
        "live_trade": False,
    }
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return {**base, "ok": False, "status": "INVALID_CLOCK", "components": {}}
    results = {}
    kwargs = {}
    if check_unit is not None:
        kwargs["check_unit"] = check_unit
    if read_json is not None:
        kwargs["read_json"] = read_json
    for name in _COMPONENTS:
        try:
            raw = component_snapshot(name, now=now, **kwargs)
        except (OSError, RuntimeError, TypeError, ValueError, KeyError):
            raw = None
        results[name] = _project(raw)
    healthy = all(
        item["operational_state"] == "HEARTBEAT_CURRENT"
        and item["unit_active"] is True
        and item["safety_evidence"] == "COMPLETE"
        for item in results.values()
    )
    return {
        **base,
        "ok": healthy,
        "status": "OPERATIONAL_OBSERVATION_ONLY" if healthy else "BLOCKED",
        "observed_at_utc": now.astimezone(timezone.utc).isoformat(),
        "components": results,
    }

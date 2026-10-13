#!/usr/bin/env python3
"""Read-only, redacted EC2 cloud runtime audit; never authorizes trading.

A single SSM audit cannot prove the user's local computer was powered off.
The script reports only bounded operational evidence from existing services.
"""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from typing import Callable


_COMPONENTS = {
    "us_livefeed": (
        "stock-razor-us-livefeed.service",
        "/run/stock-razor-us-livefeed/latest-heartbeat.json",
        "type",
        "us_opend_livefeed_heartbeat",
    ),
    "us_radar": (
        "stock-razor-us-radar.service",
        "/run/stock-razor-us-radar/latest-research-state.json",
        "type",
        "us_radar_research_heartbeat",
    ),
    "cn_observer": (
        "stock-razor-cn-eastmoney.service",
        "/run/stock-razor-cn-eastmoney/latest-observation.json",
        "schema",
        "stock_razor_cn_eastmoney_observation_v1",
    ),
    "cn_radar": (
        "stock-razor-cn-radar.service",
        "/run/stock-razor-cn-radar/latest-research-state.json",
        "type",
        "cn_radar_research_heartbeat",
    ),
}
_ALLOWED_DATA_STATUS = frozenset({"PASS", "STALE", "DEGRADED", "BLOCKED", "UNKNOWN"})
_MAX_JSON_BYTES = 5_000_000


def _service_active(unit: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "active"
    except (OSError, subprocess.TimeoutExpired):
        return False


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if result.tzinfo is None or result.utcoffset() is None:
        return None
    return result.astimezone(timezone.utc)


def _load_snapshot(path: str) -> dict | None:
    """Bounded safe read. Never return raw source data in audit output."""
    try:
        source = Path(path)
        if not source.is_file() or source.stat().st_size > _MAX_JSON_BYTES:
            return None
        with source.open(encoding="utf-8") as handle:
            obj = json.load(handle)
        return obj if isinstance(obj, dict) else None
    except (OSError, UnicodeError, ValueError):
        return None


def _sequence(payload: dict) -> int | None:
    value = payload.get("sequence")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def component_snapshot(
    name: str,
    *,
    now: datetime,
    check_unit: Callable[[str], bool] = _service_active,
    read_json: Callable[[str], dict | None] = _load_snapshot,
    max_heartbeat_age_seconds: int = 300,
    clock_after_read: Callable[[], datetime] | None = None,
) -> dict:
    """Classify operational heartbeat only; not market Data/Radar Admission."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if max_heartbeat_age_seconds <= 0:
        raise ValueError("max_heartbeat_age_seconds must be positive")

    unit, path, kind_field, kind_expected = _COMPONENTS[name]
    active = bool(check_unit(unit))
    result = {
        "component": name,
        "unit_active": active,
        "operational_state": "UNKNOWN",
        "heartbeat_age_seconds": None,
        "sequence": None,
        "repo_sha": None,
        "sample_status": None,
        "radar_analysis_latency_ms": None,
        "data_to_radar_latency_ms": None,
        "research_only": None,
        "safety_evidence": "UNKNOWN",
    }
    payload = read_json(path)
    if payload is None:
        result["operational_state"] = "HEARTBEAT_UNAVAILABLE"
        return result
    if payload.get(kind_field) != kind_expected:
        result["operational_state"] = "SCHEMA_MISMATCH"
        return result

    # A collector heartbeat may predate research_only/can_confirm_signal
    # fields. Report those as INCOMPLETE, never assume they are true/false.
    if not (
        payload.get("radar_admission") == "BLOCKED"
        and payload.get("live_trade") is False
        and payload.get("can_confirm_signal") is not True
        and payload.get("research_only") is not False
    ):
        result["operational_state"] = "SAFETY_CONTRACT_INVALID"
        result["safety_evidence"] = "INVALID"
        return result
    result["research_only"] = (
        True if payload.get("research_only") is True else None
    )
    result["safety_evidence"] = (
        "COMPLETE"
        if payload.get("research_only") is True
        and payload.get("can_confirm_signal") is False
        else "INCOMPLETE"
    )
    observed = _parse_time(payload.get("emitted_at_utc"))
    if observed is None:
        result["operational_state"] = "TIMESTAMP_INVALID"
        return result

    # Capture observation time AFTER loading the atomic heartbeat. US Radar
    # publishes ~4 Hz: a common pre-read timestamp can be overtaken by the
    # newest file during systemctl/JSON I/O and falsely look like clock skew.
    # Keep the caller's explicit clock when no post-read clock is supplied,
    # and never waive genuine future timestamps or backward wall-clock jumps.
    observed_now = clock_after_read() if clock_after_read is not None else now
    if (not isinstance(observed_now, datetime) or observed_now.tzinfo is None
            or observed_now.utcoffset() is None):
        result["operational_state"] = "TIMESTAMP_INVALID"
        return result
    if observed_now.astimezone(timezone.utc) < now.astimezone(timezone.utc):
        result["operational_state"] = "CLOCK_REVERSAL"
        return result
    age = (observed_now.astimezone(timezone.utc) - observed).total_seconds()
    if age < 0:
        result["operational_state"] = "CLOCK_REVERSAL"
        return result
    result["heartbeat_age_seconds"] = round(age, 3)
    result["sequence"] = _sequence(payload)
    sha = payload.get("worker_repo_sha") or payload.get("repo_sha")
    result["repo_sha"] = sha if isinstance(sha, str) and len(sha) == 40 and all(
        ch in "0123456789abcdef" for ch in sha.lower()
    ) else None
    status = payload.get("poll_status") or payload.get("status")
    result["sample_status"] = status if isinstance(status, str) and status in (
        _ALLOWED_DATA_STATUS | {"UNCHANGED"}
    ) else None

    # These are per-source-sequence observational fields, not fresh benchmark
    # samples and must not be counted as repeated independent data points.
    if name.endswith("_radar") and payload.get("radar_analysis_performed") is True:
        for field in ("radar_analysis_latency_ms", "data_to_radar_latency_ms"):
            value = payload.get(field)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and 0 <= value < float("inf")
            ):
                result[field] = round(value, 3)

    if not active:
        result["operational_state"] = "UNIT_INACTIVE"
    elif age > max_heartbeat_age_seconds:
        result["operational_state"] = "HEARTBEAT_STALE"
    elif result["sequence"] is None:
        result["operational_state"] = "SEQUENCE_UNKNOWN"
    else:
        result["operational_state"] = "HEARTBEAT_CURRENT"
    return result



def mcp_install_evidence(
    *,
    active: Callable[[str], bool] = _service_active,
    source: Callable[[], str] = lambda: Path(
        "/opt/stock-razor-mcp/repo/realtime_monitor/readonly_mcp_server.py"
    ).read_text(encoding="utf-8"),
    revision: Callable[[], str] = lambda: subprocess.run(
        ["git", "-C", "/opt/stock-razor-mcp/repo", "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=3, check=False,
    ).stdout.strip(),
) -> dict:
    """Read fixed installed MCP source; not authenticated protocol discovery."""
    running = active("stock-razor-mcp.service")
    tool = False
    sha = None
    try:
        tree = ast.parse(source())
        tool = any(
            isinstance(node, ast.FunctionDef)
            and node.name == "get_cloud_ops_status"
            and any(ast.unparse(d) == "mcp.tool()" for d in node.decorator_list)
            for node in tree.body
        )
    except (OSError, UnicodeError, ValueError, SyntaxError, TypeError):
        pass
    try:
        value = revision()
        if isinstance(value, str) and len(value) == 40 and all(
            c in "0123456789abcdef" for c in value
        ):
            sha = value
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        pass
    return {
        "mcp_unit_active": running is True,
        "cloud_ops_tool_in_deployed_source": tool,
        "deployed_repo_sha": sha,
        "authenticated_protocol_verified": False,
        "status": ("SOURCE_PRESENT_PROTOCOL_NOT_VERIFIED"
                   if running and tool and sha else "BLOCKED"),
    }


def audit_twice(
    *,
    interval_seconds: float = 15.0,
    check_unit: Callable[[str], bool] = _service_active,
    read_json: Callable[[str], dict | None] = _load_snapshot,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleeper: Callable[[float], None] = time.sleep,
    read_mcp: Callable[[], dict] = mcp_install_evidence,
) -> dict:
    if not 0 <= interval_seconds <= 60:
        raise ValueError("interval_seconds must be between 0 and 60")

    def sample() -> dict:
        # Each service gets its own before/after JSON-read timestamps. Do not
        # reuse one wall-clock for four files refreshed at different cadences.
        return {
            name: component_snapshot(
                name, now=clock(), check_unit=check_unit,
                read_json=read_json, clock_after_read=clock,
            )
            for name in _COMPONENTS
        }

    first = sample()
    if interval_seconds:
        sleeper(interval_seconds)
    second = sample()
    progress = {}
    for name in _COMPONENTS:
        earlier, later = first[name], second[name]
        a, b = earlier["sequence"], later["sequence"]
        progress[name] = bool(
            earlier["operational_state"] == "HEARTBEAT_CURRENT"
            and later["operational_state"] == "HEARTBEAT_CURRENT"
            and a is not None
            and b is not None
            and b > a
        )

    return {
        "schema": "stock_razor_cloud_runtime_readonly_audit_v1",
        "audit_status": "COMPLETE_WITH_GAPS" if any(
            value["operational_state"] != "HEARTBEAT_CURRENT"
            for value in second.values()
        ) else "COMPLETE",
        "measurement_scope": "AWS_SSM_RUNTIME_SNAPSHOT_ONLY",
        "aws_components": second,
        "mcp_deployment_evidence": read_mcp(),
        "heartbeat_progress_observed": progress,
        "all_components_current": all(
            x["operational_state"] == "HEARTBEAT_CURRENT"
            for x in second.values()
        ),
        "all_safety_evidence_complete": all(
            x["safety_evidence"] == "COMPLETE" for x in second.values()
        ),
        # Neither SSM nor sustained heartbeat progression proves off-PC
        # independence, currentness, data quality, or admission.
        "off_pc_independent_acquisition": "NOT_VERIFIED",
        "intraday_data_quality": "NOT_VERIFIED",
        "radar_admission": "BLOCKED",
        "live_trade": "NO",
        "can_confirm_signal": False,
        "external_notifications_sent": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval-seconds", type=float, default=15)
    args = parser.parse_args()
    result = audit_twice(interval_seconds=args.interval_seconds)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Fail-closed evidence contract for cloud runtime and PC-off independence.

This module evaluates externally supplied runtime evidence.  It performs no
deployment, provider I/O, market-data qualification, Radar admission, or trade
execution.  A worker cannot prove its own cloud independence merely by setting
flags in its own payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RuntimeHeartbeat:
    runtime_instance_id: str
    generation: int
    host_id: str
    sequence: int
    emitted_at_utc: datetime
    observer_id: str
    observer_host_id: str


@dataclass(frozen=True)
class PcOffWindow:
    user_device_id: str
    offline_from_utc: datetime
    offline_until_utc: datetime
    observer_id: str
    observer_host_id: str


@dataclass(frozen=True)
class CloudRuntimeDecision:
    verified: bool
    reason: str
    heartbeat_count: int = 0


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def evaluate_cloud_pc_off_independence(
    heartbeats: tuple[RuntimeHeartbeat, ...],
    pc_off: PcOffWindow,
    *,
    min_heartbeats: int = 3,
) -> CloudRuntimeDecision:
    if min_heartbeats < 2:
        raise ValueError("min_heartbeats must be at least 2")
    if len(heartbeats) < min_heartbeats:
        return CloudRuntimeDecision(False, "INSUFFICIENT_HEARTBEATS", len(heartbeats))

    start = _utc(pc_off.offline_from_utc)
    end = _utc(pc_off.offline_until_utc)
    if end <= start:
        return CloudRuntimeDecision(False, "INVALID_PC_OFF_WINDOW", len(heartbeats))
    if not pc_off.user_device_id.strip():
        return CloudRuntimeDecision(False, "MISSING_USER_DEVICE_ID", len(heartbeats))
    if pc_off.observer_host_id == pc_off.user_device_id:
        return CloudRuntimeDecision(False, "PC_OFF_SELF_ATTESTATION_FORBIDDEN", len(heartbeats))

    runtime_ids = {item.runtime_instance_id for item in heartbeats}
    generations = {item.generation for item in heartbeats}
    host_ids = {item.host_id for item in heartbeats}
    observer_hosts = {item.observer_host_id for item in heartbeats}
    if len(runtime_ids) != 1 or len(generations) != 1 or len(host_ids) != 1:
        return CloudRuntimeDecision(False, "RUNTIME_IDENTITY_NOT_STABLE", len(heartbeats))
    if any(not value.strip() for value in runtime_ids | host_ids | observer_hosts):
        return CloudRuntimeDecision(False, "MISSING_RUNTIME_PROVENANCE", len(heartbeats))

    runtime_host = next(iter(host_ids))
    if runtime_host == pc_off.user_device_id:
        return CloudRuntimeDecision(False, "RUNTIME_DEPENDS_ON_USER_DEVICE", len(heartbeats))
    if runtime_host in observer_hosts:
        return CloudRuntimeDecision(False, "RUNTIME_SELF_ATTESTATION_FORBIDDEN", len(heartbeats))

    ordered = sorted(heartbeats, key=lambda item: item.sequence)
    sequences = [item.sequence for item in ordered]
    if any(b <= a for a, b in zip(sequences, sequences[1:])):
        return CloudRuntimeDecision(False, "HEARTBEAT_SEQUENCE_NOT_STRICT", len(heartbeats))

    times = [_utc(item.emitted_at_utc) for item in ordered]
    if any(b <= a for a, b in zip(times, times[1:])):
        return CloudRuntimeDecision(False, "HEARTBEAT_TIME_NOT_STRICT", len(heartbeats))
    if times[0] < start or times[-1] > end:
        return CloudRuntimeDecision(False, "HEARTBEATS_OUTSIDE_PC_OFF_WINDOW", len(heartbeats))
    if times[0] == times[-1]:
        return CloudRuntimeDecision(False, "NO_SUSTAINED_RUNTIME_WINDOW", len(heartbeats))

    if pc_off.observer_host_id == runtime_host:
        return CloudRuntimeDecision(False, "PC_OFF_OBSERVER_NOT_INDEPENDENT", len(heartbeats))

    return CloudRuntimeDecision(True, "CLOUD_PC_OFF_INDEPENDENCE_PROVEN", len(heartbeats))

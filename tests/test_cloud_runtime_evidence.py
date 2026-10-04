from datetime import datetime, timedelta, timezone

from src.services.live_feed.cloud_runtime_evidence import (
    PcOffWindow,
    RuntimeHeartbeat,
    evaluate_cloud_pc_off_independence,
)

T0 = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)


def hb(seq, *, runtime="rt-1", generation=3, host="aws-i-1", observer_host="audit-host"):
    return RuntimeHeartbeat(
        runtime_instance_id=runtime,
        generation=generation,
        host_id=host,
        sequence=seq,
        emitted_at_utc=T0 + timedelta(minutes=seq),
        observer_id="external-auditor",
        observer_host_id=observer_host,
    )


def window(*, observer_host="pc-off-auditor"):
    return PcOffWindow(
        user_device_id="DESKTOP-USER",
        offline_from_utc=T0,
        offline_until_utc=T0 + timedelta(minutes=10),
        observer_id="pc-off-observer",
        observer_host_id=observer_host,
    )


def test_independent_sustained_runtime_can_pass():
    decision = evaluate_cloud_pc_off_independence((hb(1), hb(2), hb(3)), window())
    assert decision.verified is True
    assert decision.reason == "CLOUD_PC_OFF_INDEPENDENCE_PROVEN"


def test_runtime_cannot_run_on_user_device():
    heartbeats = tuple(hb(i, host="DESKTOP-USER") for i in (1, 2, 3))
    decision = evaluate_cloud_pc_off_independence(heartbeats, window())
    assert decision.verified is False
    assert decision.reason == "RUNTIME_DEPENDS_ON_USER_DEVICE"


def test_runtime_cannot_self_attest_heartbeats():
    heartbeats = tuple(hb(i, observer_host="aws-i-1") for i in (1, 2, 3))
    decision = evaluate_cloud_pc_off_independence(heartbeats, window())
    assert decision.reason == "RUNTIME_SELF_ATTESTATION_FORBIDDEN"


def test_pc_off_observer_cannot_be_user_device():
    decision = evaluate_cloud_pc_off_independence(
        (hb(1), hb(2), hb(3)),
        window(observer_host="DESKTOP-USER"),
    )
    assert decision.reason == "PC_OFF_SELF_ATTESTATION_FORBIDDEN"


def test_generation_change_fails_closed():
    decision = evaluate_cloud_pc_off_independence(
        (hb(1), hb(2, generation=4), hb(3)),
        window(),
    )
    assert decision.reason == "RUNTIME_IDENTITY_NOT_STABLE"


def test_too_few_heartbeats_do_not_prove_cloud_runtime():
    decision = evaluate_cloud_pc_off_independence((hb(1),), window())
    assert decision.reason == "INSUFFICIENT_HEARTBEATS"


def test_heartbeat_outside_pc_off_window_fails():
    late = RuntimeHeartbeat(
        runtime_instance_id="rt-1",
        generation=3,
        host_id="aws-i-1",
        sequence=11,
        emitted_at_utc=T0 + timedelta(minutes=11),
        observer_id="external-auditor",
        observer_host_id="audit-host",
    )
    decision = evaluate_cloud_pc_off_independence((hb(1), hb(2), late), window())
    assert decision.reason == "HEARTBEATS_OUTSIDE_PC_OFF_WINDOW"

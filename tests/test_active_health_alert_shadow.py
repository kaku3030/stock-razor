"""Bounded negative controls for advisory-only active health alerts."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace

from src.services.active_health_alert_shadow import (
    HealthAlertEvidence,
    ShadowAlertState,
    project_health_alert_shadow,
)

NOW = datetime(2026, 10, 11, 2, 0, tzinfo=timezone.utc)
BASE = HealthAlertEvidence(
    source_family="us_opend",
    source_revision="a" * 40,
    runtime_generation="worker-1",
    episode_id="episode-42",
    event_kind="MARKET_DATA_STALE",
    session_state="OPEN",
    observed_at_utc=NOW - timedelta(seconds=15),
    source_status="STALE",
    source_identity_qualified=True,
    clock_qualified=True,
)


def test_market_open_candidate_still_never_sends_or_trades():
    result = project_health_alert_shadow(BASE, now_utc=NOW)
    assert result.state == ShadowAlertState.CANDIDATE
    assert result.dedup_key is not None and len(result.dedup_key) == 64
    assert result.advisory_only is True
    assert result.send_authorized is False
    assert result.order_mutation_allowed is False


def test_replay_same_episode_has_stable_key_but_new_episode_changes_it():
    old = project_health_alert_shadow(BASE, now_utc=NOW)
    replay = project_health_alert_shadow(BASE, now_utc=NOW + timedelta(seconds=1))
    new_episode = project_health_alert_shadow(
        replace(BASE, episode_id="episode-43"), now_utc=NOW
    )
    assert old.dedup_key == replay.dedup_key
    assert old.dedup_key != new_episode.dedup_key


def test_closed_weekend_suppresses_market_data_false_outage():
    result = project_health_alert_shadow(
        replace(BASE, session_state="CLOSED"), now_utc=NOW
    )
    assert result.state == ShadowAlertState.SUPPRESSED
    assert result.reason == "MARKET_CLOSED_NOT_AN_OUTAGE"
    assert result.dedup_key is None


def test_unknown_session_or_unqualified_evidence_cannot_page():
    for change in (
        {"session_state": "UNKNOWN"},
        {"clock_qualified": False},
        {"source_identity_qualified": False},
        {"source_revision": "UNKNOWN"},
        {"episode_id": ""},
        {"source_family": "unknown_provider"},
    ):
        result = project_health_alert_shadow(replace(BASE, **change), now_utc=NOW)
        assert result.state == ShadowAlertState.BLOCKED
        assert result.send_authorized is False


def test_invalid_or_future_timestamps_fail_closed():
    for observed in (
        NOW + timedelta(seconds=1),
        NOW - timedelta(hours=2),
        NOW.replace(tzinfo=None),
    ):
        result = project_health_alert_shadow(
            replace(BASE, observed_at_utc=observed), now_utc=NOW
        )
        assert result.state == ShadowAlertState.BLOCKED
    assert project_health_alert_shadow(BASE, now_utc=NOW.replace(tzinfo=None)).state == ShadowAlertState.BLOCKED


def test_heartbeat_can_be_advisory_during_market_close_only_if_worker_expected():
    evidence = replace(BASE, event_kind="WORKER_HEARTBEAT_STALE", session_state="CLOSED")
    blocked = project_health_alert_shadow(evidence, now_utc=NOW)
    assert blocked.state == ShadowAlertState.BLOCKED
    candidate = project_health_alert_shadow(
        replace(evidence, worker_expected_running=True), now_utc=NOW
    )
    assert candidate.state == ShadowAlertState.CANDIDATE
    assert candidate.send_authorized is False


def test_no_stale_incident_and_invalid_ttl():
    assert project_health_alert_shadow(
        replace(BASE, source_status="HEALTHY"), now_utc=NOW
    ).state == ShadowAlertState.SUPPRESSED
    for ttl in (0, -1, True):
        assert project_health_alert_shadow(
            BASE, now_utc=NOW, max_evidence_age_seconds=ttl
        ).state == ShadowAlertState.BLOCKED


def test_no_raw_payload_or_secret_in_projection():
    result = project_health_alert_shadow(
        replace(BASE, episode_id="NOT_AN_AUTHORIZED_EPISODE/secret"), now_utc=NOW
    )
    assert result.state == ShadowAlertState.BLOCKED
    assert "secret" not in str(result)

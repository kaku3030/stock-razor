"""Pure, fail-closed advisory projection for market-health Shadow alerts.

No provider calls, notifications, state mutation, scheduler, or order I/O.
The canonical AI Monitor notification owner may consume this projection only
after independent acceptance; this file is NOT a sender or runtime owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
import re


class ShadowAlertState(StrEnum):
    BLOCKED = "BLOCKED"
    SUPPRESSED = "SUPPRESSED"
    CANDIDATE = "CANDIDATE"


SOURCE_FAMILIES = frozenset(("us_opend", "cn_tickflow", "cn_eastmoney_tencent"))
EVENT_KINDS = frozenset(("MARKET_DATA_STALE", "WORKER_HEARTBEAT_STALE"))
SESSION_STATES = frozenset(("OPEN", "CLOSED", "UNKNOWN"))
IDENTITY = re.compile(r"^[a-zA-Z0-9_.:-]{1,80}$")
REVISION = re.compile(r"^[a-f0-9]{40}$")


@dataclass(frozen=True)
class HealthAlertEvidence:
    source_family: str
    source_revision: str
    runtime_generation: str
    episode_id: str
    event_kind: str
    session_state: str
    observed_at_utc: datetime
    source_status: str
    source_identity_qualified: bool
    clock_qualified: bool
    worker_expected_running: bool = False


@dataclass(frozen=True)
class ShadowAlertProjection:
    state: ShadowAlertState
    reason: str
    event_kind: str
    dedup_key: str | None
    advisory_only: bool = True
    send_authorized: bool = False
    order_mutation_allowed: bool = False


def project_health_alert_shadow(
    evidence: HealthAlertEvidence,
    *,
    now_utc: datetime,
    max_evidence_age_seconds: int = 300,
) -> ShadowAlertProjection:
    """Project one *externally identified episode*, without sending alerts.

    The caller owns the episode identity and its durable transition ledger.
    This function deliberately cannot manufacture recovery from stale evidence.
    """

    def blocked(reason: str) -> ShadowAlertProjection:
        return ShadowAlertProjection(ShadowAlertState.BLOCKED, reason, evidence.event_kind, None)

    def suppressed(reason: str) -> ShadowAlertProjection:
        return ShadowAlertProjection(ShadowAlertState.SUPPRESSED, reason, evidence.event_kind, None)

    if (
        not isinstance(evidence.source_family, str)
        or not isinstance(evidence.event_kind, str)
        or evidence.source_family not in SOURCE_FAMILIES
        or evidence.event_kind not in EVENT_KINDS
    ):
        return blocked("UNSUPPORTED_SOURCE_OR_EVENT")
    if not isinstance(evidence.session_state, str) or evidence.session_state not in SESSION_STATES:
        return blocked("UNKNOWN_SESSION")
    if not (
        isinstance(evidence.source_revision, str)
        and REVISION.fullmatch(evidence.source_revision)
        and isinstance(evidence.runtime_generation, str)
        and IDENTITY.fullmatch(evidence.runtime_generation)
        and isinstance(evidence.episode_id, str)
        and IDENTITY.fullmatch(evidence.episode_id)
    ):
        return blocked("EVIDENCE_IDENTITY_UNVERIFIED")
    if not (evidence.source_identity_qualified is True and evidence.clock_qualified is True):
        return blocked("SOURCE_OR_CLOCK_UNVERIFIED")
    if (
        not isinstance(max_evidence_age_seconds, int)
        or isinstance(max_evidence_age_seconds, bool)
        or max_evidence_age_seconds <= 0
    ):
        return blocked("INVALID_TTL")
    if not isinstance(now_utc, datetime) or not isinstance(evidence.observed_at_utc, datetime):
        return blocked("CLOCK_INVALID")
    if (
        now_utc.tzinfo is None or now_utc.utcoffset() is None
        or evidence.observed_at_utc.tzinfo is None
        or evidence.observed_at_utc.utcoffset() is None
    ):
        return blocked("CLOCK_INVALID")
    age = (
        now_utc.astimezone(timezone.utc)
        - evidence.observed_at_utc.astimezone(timezone.utc)
    ).total_seconds()
    if age < 0 or age > max_evidence_age_seconds:
        return blocked("EVIDENCE_FUTURE_OR_STALE")
    if evidence.event_kind == "MARKET_DATA_STALE":
        if evidence.session_state == "CLOSED":
            return suppressed("MARKET_CLOSED_NOT_AN_OUTAGE")
        if evidence.session_state != "OPEN":
            return blocked("SESSION_NOT_PROVEN_OPEN")
    if evidence.event_kind == "WORKER_HEARTBEAT_STALE":
        if evidence.worker_expected_running is not True:
            return blocked("WORKER_SCHEDULE_NOT_PROVEN")

    if evidence.source_status != "STALE":
        return suppressed("NO_VERIFIED_STALE_INCIDENT")

    identity = "|".join((
        "stock-razor-health-alert-shadow-v0_1",
        evidence.source_family,
        evidence.event_kind,
        evidence.runtime_generation,
        evidence.episode_id,
    ))
    key = sha256(identity.encode("utf-8")).hexdigest()
    return ShadowAlertProjection(
        ShadowAlertState.CANDIDATE,
        "ADVISORY_CANDIDATE_NO_DELIVERY_PERMISSION",
        evidence.event_kind,
        key,
    )

"""Fail-closed, read-only admission of qualified futures evidence to Radar."""

from __future__ import annotations

from dataclasses import dataclass

from data_provider.live_feed_types import DeliveryMode, ProviderEvent
from src.services.live_feed.qualification import StreamQualification, QualificationStatus


@dataclass(frozen=True)
class FuturesRadarAdmission:
    accepted: bool
    reason: str


def admit_futures_to_radar(
    event: ProviderEvent,
    qualification: StreamQualification,
) -> FuturesRadarAdmission:
    """Accept only controller-qualified realtime evidence; never infer it."""

    if event.delivery_mode is not DeliveryMode.REALTIME:
        return FuturesRadarAdmission(False, "DELIVERY_MODE_NOT_REALTIME")
    if qualification.lifecycle_state.value != "LIVE":
        return FuturesRadarAdmission(False, "LIVEFEED_NOT_QUALIFIED")
    if qualification.currentness.status is not QualificationStatus.PROVEN:
        return FuturesRadarAdmission(False, "CURRENTNESS_NOT_PROVEN")
    if qualification.continuity.status is not QualificationStatus.PROVEN:
        return FuturesRadarAdmission(False, "CONTINUITY_NOT_PROVEN")
    if event.semantic_stream_key != qualification.semantic_stream_key:
        return FuturesRadarAdmission(False, "STREAM_IDENTITY_MISMATCH")
    return FuturesRadarAdmission(True, "QUALIFIED_FUTURES_EVIDENCE")

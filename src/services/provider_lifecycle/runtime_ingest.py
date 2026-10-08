"""Provider-specific runtime evidence adapters.

The adapters in this module translate existing runtime facts into
ProviderRuntimeObservation values. They do not make Data Admission, Radar
Admission, fallback, spend, alert, or execution decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping

from .contract import ProviderHealthState
from .observer import (
    EvidenceProvenance,
    ObservedProviderValue,
    ProviderRuntimeObservation,
    ProviderRuntimeObserver,
    RuntimeProviderSnapshot,
)


class ProviderRuntimeIngestError(ValueError):
    """Raised when runtime evidence is malformed or violates frozen governance."""


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderRuntimeIngestError(f"{field_name} must be a non-empty string")
    if value != value.strip():
        raise ProviderRuntimeIngestError(f"{field_name} must not contain outer whitespace")
    return value


def _exact_sha(value: object) -> str:
    sha = _text(value, "repo_sha")
    if (
        sha != sha.lower()
        or len(sha) != 40
        or any(ch not in "0123456789abcdef" for ch in sha)
    ):
        raise ProviderRuntimeIngestError(
            "repo_sha must be an exact 40-character lowercase git SHA"
        )
    return sha


def _positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProviderRuntimeIngestError(f"{field_name} must be a positive integer")
    return value


def _nonnegative_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProviderRuntimeIngestError(f"{field_name} must be a non-negative integer")
    return value


def _parse_aware_timestamp(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _text(value, field_name)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ProviderRuntimeIngestError(
                f"{field_name} must be an ISO-8601 timestamp"
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProviderRuntimeIngestError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ProviderRuntimeIngestError(f"{field_name} must be a list or tuple")
    normalized: list[str] = []
    for item in value:
        normalized.append(_text(item, field_name))
    return tuple(normalized)


def _lifecycle_health(value: object) -> tuple[ProviderHealthState, str | None]:
    state = _text(value, "controller_lifecycle").upper()
    if state == "LIVE":
        raise ProviderRuntimeIngestError(
            "controller_lifecycle LIVE is forbidden by the current runtime contract"
        )
    if state == "FAILED":
        return ProviderHealthState.FAILED, "CONTROLLER_FAILED"
    if state in {"DEGRADED", "RECONNECTING", "DISCONNECTED"}:
        return ProviderHealthState.DEGRADED, f"CONTROLLER_{state}"
    if state in {"CONNECTED", "CONNECTING", "SUBSCRIBING"}:
        # Positive transport state alone is insufficient to prove provider
        # health. Keep UNKNOWN instead of optimistic HEALTHY promotion.
        return ProviderHealthState.UNKNOWN, None
    raise ProviderRuntimeIngestError(
        f"unsupported controller_lifecycle: {state}"
    )


def _failure_reason(
    *,
    health_state: ProviderHealthState,
    default_reason: str | None,
    findings: tuple[str, ...],
) -> str | None:
    if health_state not in {ProviderHealthState.FAILED, ProviderHealthState.DEGRADED}:
        return None
    if findings:
        return findings[-1][:240]
    return default_reason


def build_moomoo_opend_observation_from_livefeed_heartbeat(
    payload: Mapping[str, object],
) -> ProviderRuntimeObservation:
    """Translate one verified US OpenD live-feed heartbeat into lifecycle evidence.

    This function intentionally does not derive freshness, latency, coverage,
    DataAdmission, or HEALTHY state from heartbeat receipt time, REALTIME
    delivery mode, bar closure, or canonical-export success.
    """

    if not isinstance(payload, Mapping):
        raise ProviderRuntimeIngestError("heartbeat payload must be a mapping")
    if payload.get("type") != "us_opend_livefeed_heartbeat":
        raise ProviderRuntimeIngestError("unexpected heartbeat type")
    if payload.get("radar_admission") != "BLOCKED":
        raise ProviderRuntimeIngestError(
            "heartbeat must preserve RADAR_ADMISSION=BLOCKED"
        )
    if payload.get("live_trade") is not False:
        raise ProviderRuntimeIngestError("heartbeat must preserve LIVE_TRADE=NO")

    runtime_id = _text(payload.get("runtime_instance_id"), "runtime_instance_id")
    repo_sha = _exact_sha(payload.get("repo_sha"))
    sequence = _positive_int(payload.get("sequence"), "sequence")
    observed_at = _parse_aware_timestamp(payload.get("emitted_at_utc"), "emitted_at_utc")

    event_count = _nonnegative_int(payload.get("event_count"), "event_count")
    accepted_event_count = _nonnegative_int(
        payload.get("accepted_event_count"),
        "accepted_event_count",
    )
    if accepted_event_count < event_count:
        raise ProviderRuntimeIngestError(
            "accepted_event_count must be >= event_count"
        )

    health_state, default_reason = _lifecycle_health(
        payload.get("controller_lifecycle")
    )
    findings = _string_tuple(
        payload.get("controller_findings_tail"),
        "controller_findings_tail",
    )
    failure_reason = _failure_reason(
        health_state=health_state,
        default_reason=default_reason,
        findings=findings,
    )

    symbols = _string_tuple(payload.get("symbols"), "symbols")
    subscribed = _string_tuple(payload.get("subscribed"), "subscribed")
    canonical_export = payload.get("canonical_snapshot_export")
    if canonical_export is None:
        canonical_export = {}
    if not isinstance(canonical_export, Mapping):
        raise ProviderRuntimeIngestError(
            "canonical_snapshot_export must be a mapping"
        )

    canonical_status = str(canonical_export.get("status") or "UNKNOWN").strip().upper()
    canonical_error = canonical_export.get("error")
    if canonical_error is not None:
        canonical_error = _text(canonical_error, "canonical_snapshot_export.error")

    capability_facts = MappingProxyType({
        "heartbeat_type": "us_opend_livefeed_heartbeat",
        "host_id": _text(payload.get("host_id"), "host_id"),
        "sequence": sequence,
        "controller_lifecycle": _text(
            payload.get("controller_lifecycle"),
            "controller_lifecycle",
        ).upper(),
        "controller_failure_class": str(
            payload.get("controller_failure_class") or "UNKNOWN"
        ).strip().upper(),
        "event_count": event_count,
        "accepted_event_count": accepted_event_count,
        "symbol_count": len(symbols),
        "subscribed_count": len(subscribed),
        "delivery_mode": str(payload.get("delivery_mode") or "UNKNOWN").strip().upper(),
        "bar_closure": str(payload.get("bar_closure") or "UNPROVEN").strip().upper(),
        "market_state_us": str(payload.get("market_state_us") or "UNKNOWN").strip(),
        "market_state_evidence": str(
            payload.get("market_state_evidence") or "UNKNOWN"
        ).strip().upper(),
        "canonical_snapshot_status": canonical_status,
        "canonical_snapshot_error": canonical_error,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    })

    def observed(
        field_name: str,
        value: object,
        *,
        error_code: str | None = None,
    ) -> ObservedProviderValue:
        return ObservedProviderValue(
            value=value,
            provenance=EvidenceProvenance(
                observed_at=observed_at,
                source="us_opend_livefeed_heartbeat",
                runtime_id=runtime_id,
                repo_sha=repo_sha,
                error_code=error_code,
                evidence_id=(
                    f"us-opend:{runtime_id}:{sequence}:{field_name}"
                ),
            ),
        )

    fields: dict[str, ObservedProviderValue] = {
        "health_state": observed(
            "health_state",
            health_state,
            error_code=default_reason,
        ),
        "failure_reason": observed(
            "failure_reason",
            failure_reason,
            error_code=default_reason,
        ),
        "capabilities": observed("capabilities", capability_facts),
    }

    if health_state in {ProviderHealthState.FAILED, ProviderHealthState.DEGRADED}:
        fields["last_failure"] = observed(
            "last_failure",
            observed_at,
            error_code=default_reason,
        )

    if event_count > 0:
        last_push = _parse_aware_timestamp(payload.get("last_push_utc"), "last_push_utc")
        if last_push > observed_at:
            raise ProviderRuntimeIngestError(
                "last_push_utc must not be after emitted_at_utc"
            )
        fields["last_success"] = observed("last_success", last_push)

    return ProviderRuntimeObservation(
        provider_id="moomoo_opend",
        fields=fields,
    )


def ingest_moomoo_opend_livefeed_heartbeat(
    observer: ProviderRuntimeObserver,
    payload: Mapping[str, object],
) -> RuntimeProviderSnapshot:
    """Parse then ingest one OpenD heartbeat into the lifecycle observer."""

    return observer.ingest(
        build_moomoo_opend_observation_from_livefeed_heartbeat(payload)
    )

"""Provider-specific runtime evidence adapters.

The adapters in this module translate existing runtime facts into
ProviderRuntimeObservation values. They do not make Data Admission, Radar
Admission, fallback, spend, alert, or execution decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping, Sequence

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

    runtime_id = _safe_probe_token(
        payload.get("runtime_instance_id"),
        "runtime_instance_id",
        required=True,
    )
    assert runtime_id is not None
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


_CN_CLOUD_SCHEMA = "stock_razor_cn_eastmoney_observation_v1"
_CN_PROVIDER_POLICY = "EASTMONEY_PRIMARY_TENCENT_FALLBACK"


def _required_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProviderRuntimeIngestError(f"{field_name} must be a mapping")
    return value


def _optional_exact_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


def _cn_failure_summary(prefix: str, reasons: list[str]) -> str:
    normalized = sorted({reason for reason in reasons if reason})
    suffix = "|".join(normalized) if normalized else "UNKNOWN"
    return f"{prefix}:{suffix}"[:240]


def build_cn_provider_observations_from_cloud_snapshot(
    payload: Mapping[str, object],
) -> tuple[ProviderRuntimeObservation, ...]:
    """Translate the governed CN cloud snapshot into provider-specific evidence.

    Static provider_lineages are identity metadata only. Provider evidence is
    derived exclusively from per-frame provider_used / fallback_from / errors.
    Route currentness and request latency are not promoted to provider
    freshness_ms or latency_ms.
    """

    if not isinstance(payload, Mapping):
        raise ProviderRuntimeIngestError("CN cloud payload must be a mapping")
    if payload.get("schema") != _CN_CLOUD_SCHEMA:
        raise ProviderRuntimeIngestError("unexpected CN cloud observation schema")
    if payload.get("provider_policy") != _CN_PROVIDER_POLICY:
        raise ProviderRuntimeIngestError("unexpected CN provider policy")
    if payload.get("radar_admission") != "BLOCKED":
        raise ProviderRuntimeIngestError(
            "CN cloud observation must preserve RADAR_ADMISSION=BLOCKED"
        )
    if payload.get("live_trade") is not False:
        raise ProviderRuntimeIngestError(
            "CN cloud observation must preserve LIVE_TRADE=NO"
        )
    if payload.get("research_only") is not True:
        raise ProviderRuntimeIngestError(
            "CN cloud observation must remain research_only"
        )
    if payload.get("can_confirm_signal") is not False:
        raise ProviderRuntimeIngestError(
            "CN cloud observation must keep can_confirm_signal=false"
        )

    runtime_id = _safe_probe_token(
        payload.get("runtime_instance_id"),
        "runtime_instance_id",
        required=True,
    )
    assert runtime_id is not None
    repo_sha = _exact_sha(payload.get("repo_sha"))
    sequence = _positive_int(payload.get("sequence"), "sequence")
    observed_at = _parse_aware_timestamp(
        payload.get("emitted_at_utc"),
        "emitted_at_utc",
    )
    host_id = _text(payload.get("host_id"), "host_id")
    observer_status = _text(payload.get("status"), "status").upper()
    if observer_status not in {"PASS", "PARTIAL", "BLOCKED"}:
        raise ProviderRuntimeIngestError(
            f"unsupported CN observer status: {observer_status}"
        )

    for field_name in (
        "intraday_timestamp_semantics_proven",
        "intraday_currentness_proven",
    ):
        if not isinstance(payload.get(field_name), bool):
            raise ProviderRuntimeIngestError(
                f"{field_name} must be a boolean"
            )

    lineages = _string_tuple(payload.get("provider_lineages"), "provider_lineages")
    if set(lineages) != {"eastmoney", "tencent"} or len(lineages) != 2:
        raise ProviderRuntimeIngestError(
            "provider_lineages must contain exactly eastmoney and tencent"
        )

    declared_used = _string_tuple(payload.get("providers_used"), "providers_used")
    if len(set(declared_used)) != len(declared_used):
        raise ProviderRuntimeIngestError("providers_used must not contain duplicates")
    if any(provider not in {"eastmoney", "tencent"} for provider in declared_used):
        raise ProviderRuntimeIngestError(
            "providers_used contains unsupported provider"
        )

    symbols = _required_mapping(payload.get("symbols"), "symbols")
    if not symbols:
        raise ProviderRuntimeIngestError(
            "CN cloud observation contains no provider-specific frame evidence"
        )

    eastmoney_success: list[str] = []
    eastmoney_fail: list[str] = []
    eastmoney_reasons: list[str] = []
    tencent_success: list[str] = []
    tencent_fail: list[str] = []
    tencent_reasons: list[str] = []
    tencent_currentness: list[str] = []
    actual_used: set[str] = set()
    frame_count = 0

    for symbol, symbol_value in symbols.items():
        symbol_id = _text(symbol, "symbols key")
        symbol_payload = _required_mapping(
            symbol_value,
            f"symbols[{symbol_id}]",
        )
        timeframes = _required_mapping(
            symbol_payload.get("timeframes"),
            f"symbols[{symbol_id}].timeframes",
        )
        if not timeframes:
            raise ProviderRuntimeIngestError(
                f"symbols[{symbol_id}].timeframes must not be empty"
            )

        for timeframe, frame_value in timeframes.items():
            frame_name = _text(timeframe, "timeframe")
            frame = _required_mapping(
                frame_value,
                f"symbols[{symbol_id}].timeframes[{frame_name}]",
            )
            frame_count += 1
            frame_id = f"{symbol_id}:{frame_name}"
            frame_status = _text(
                frame.get("status"),
                f"{frame_id}.status",
            ).upper()
            if frame_status not in {"PASS", "BLOCKED"}:
                raise ProviderRuntimeIngestError(
                    f"unsupported frame status for {frame_id}: {frame_status}"
                )

            provider_used = _optional_exact_text(
                frame.get("provider_used"),
                f"{frame_id}.provider_used",
            )
            provider_lineage = _optional_exact_text(
                frame.get("provider_lineage"),
                f"{frame_id}.provider_lineage",
            )
            fallback_from = _optional_exact_text(
                frame.get("fallback_from"),
                f"{frame_id}.fallback_from",
            )
            fallback_reason = _optional_exact_text(
                frame.get("fallback_reason"),
                f"{frame_id}.fallback_reason",
            )
            frame_error = _optional_exact_text(
                frame.get("error"),
                f"{frame_id}.error",
            )

            for field_name, value in (
                ("provider_used", provider_used),
                ("provider_lineage", provider_lineage),
                ("fallback_from", fallback_from),
            ):
                if value is not None and value != value.lower():
                    raise ProviderRuntimeIngestError(
                        f"{frame_id}.{field_name} must be lowercase"
                    )

            if provider_used == "eastmoney":
                if frame_status != "PASS":
                    raise ProviderRuntimeIngestError(
                        f"{frame_id} eastmoney success must be PASS"
                    )
                if provider_lineage != "eastmoney" or fallback_from is not None:
                    raise ProviderRuntimeIngestError(
                        f"{frame_id} eastmoney lineage/fallback mismatch"
                    )
                actual_used.add("eastmoney")
                eastmoney_success.append(frame_id)
                continue

            if provider_used == "tencent":
                if frame_status != "PASS":
                    raise ProviderRuntimeIngestError(
                        f"{frame_id} tencent success must be PASS"
                    )
                if provider_lineage != "tencent" or fallback_from != "eastmoney":
                    raise ProviderRuntimeIngestError(
                        f"{frame_id} tencent fallback lineage mismatch"
                    )
                actual_used.add("tencent")
                tencent_success.append(frame_id)
                eastmoney_fail.append(frame_id)
                eastmoney_reasons.append(
                    fallback_reason or "FALLBACK_FROM_EASTMONEY"
                )
                currentness = _text(
                    frame.get("currentness") or "UNPROVEN",
                    f"{frame_id}.currentness",
                ).upper()
                if currentness not in {"PROVEN", "UNPROVEN"}:
                    raise ProviderRuntimeIngestError(
                        f"{frame_id}.currentness must be PROVEN or UNPROVEN"
                    )
                if currentness == "PROVEN":
                    tencent_currentness.append(frame_id)
                continue

            if provider_used is not None:
                raise ProviderRuntimeIngestError(
                    f"{frame_id} contains unsupported provider_used: {provider_used}"
                )
            if provider_lineage is not None:
                raise ProviderRuntimeIngestError(
                    f"{frame_id} cannot have provider_lineage without provider_used"
                )
            if frame_status != "BLOCKED":
                raise ProviderRuntimeIngestError(
                    f"{frame_id} missing provider_used must be BLOCKED"
                )

            if fallback_from == "eastmoney":
                eastmoney_fail.append(frame_id)
                combined_reason = fallback_reason or frame_error or "EASTMONEY_BLOCKED"
                primary_reason = combined_reason.split("|TENCENT:", 1)[0]
                eastmoney_reasons.append(primary_reason or "EASTMONEY_BLOCKED")
                if "|TENCENT:" in combined_reason:
                    tencent_fail.append(frame_id)
                    tencent_reason = combined_reason.split("|TENCENT:", 1)[1]
                    tencent_reasons.append(tencent_reason or "TENCENT_BLOCKED")
            elif fallback_from is not None:
                raise ProviderRuntimeIngestError(
                    f"{frame_id} contains unsupported fallback_from: {fallback_from}"
                )

    if set(declared_used) != actual_used:
        raise ProviderRuntimeIngestError(
            "providers_used does not match per-frame provider_used evidence"
        )

    if not (
        eastmoney_success
        or eastmoney_fail
        or tencent_success
        or tencent_fail
    ):
        raise ProviderRuntimeIngestError(
            "CN cloud observation contains no attributable provider evidence"
        )

    common_capabilities = {
        "observer_schema": _CN_CLOUD_SCHEMA,
        "host_id": host_id,
        "sequence": sequence,
        "provider_policy": _CN_PROVIDER_POLICY,
        "observer_status": observer_status,
        "symbol_count": len(symbols),
        "frame_count": frame_count,
        "intraday_timestamp_semantics_proven": payload[
            "intraday_timestamp_semantics_proven"
        ],
        "intraday_currentness_proven": payload[
            "intraday_currentness_proven"
        ],
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }

    def observation_for(
        provider_id: str,
        *,
        successes: list[str],
        failures: list[str],
        failure_reasons: list[str],
        extra_capabilities: Mapping[str, object],
    ) -> ProviderRuntimeObservation:
        health_state = (
            ProviderHealthState.DEGRADED
            if failures
            else ProviderHealthState.UNKNOWN
        )
        error_code = None
        failure_reason = None
        if failures:
            error_code = (
                "EASTMONEY_FALLBACK_OBSERVED"
                if provider_id == "eastmoney"
                else "TENCENT_FALLBACK_FAILED"
            )
            failure_reason = _cn_failure_summary(
                error_code,
                failure_reasons,
            )

        capabilities = MappingProxyType({
            **common_capabilities,
            "provider_id": provider_id,
            "success_frame_count": len(successes),
            "failure_frame_count": len(failures),
            "success_frames": tuple(sorted(successes)),
            "failure_frames": tuple(sorted(failures)),
            **extra_capabilities,
        })

        def observed(
            field_name: str,
            value: object,
        ) -> ObservedProviderValue:
            return ObservedProviderValue(
                value=value,
                provenance=EvidenceProvenance(
                    observed_at=observed_at,
                    source="cn_eastmoney_cloud_observation",
                    runtime_id=runtime_id,
                    repo_sha=repo_sha,
                    error_code=error_code,
                    evidence_id=(
                        f"cn-cloud:{runtime_id}:{sequence}:{provider_id}:{field_name}"
                    ),
                ),
            )

        fields: dict[str, ObservedProviderValue] = {
            "health_state": observed("health_state", health_state),
            "failure_reason": observed("failure_reason", failure_reason),
            "capabilities": observed("capabilities", capabilities),
        }
        if failures:
            fields["last_failure"] = observed("last_failure", observed_at)
        return ProviderRuntimeObservation(
            provider_id=provider_id,
            fields=fields,
        )

    observations: list[ProviderRuntimeObservation] = []
    if eastmoney_success or eastmoney_fail:
        observations.append(observation_for(
            "eastmoney",
            successes=eastmoney_success,
            failures=eastmoney_fail,
            failure_reasons=eastmoney_reasons,
            extra_capabilities={
                "direct_success_frame_count": len(eastmoney_success),
                "fallback_trigger_frame_count": len(eastmoney_fail),
            },
        ))
    if tencent_success or tencent_fail:
        observations.append(observation_for(
            "tencent",
            successes=tencent_success,
            failures=tencent_fail,
            failure_reasons=tencent_reasons,
            extra_capabilities={
                "fallback_success_frame_count": len(tencent_success),
                "fallback_failure_frame_count": len(tencent_fail),
                "currentness_proven_frames": tuple(sorted(tencent_currentness)),
            },
        ))
    return tuple(observations)


def ingest_cn_cloud_observation(
    observer: ProviderRuntimeObserver,
    payload: Mapping[str, object],
) -> tuple[RuntimeProviderSnapshot, ...]:
    """Ingest provider-specific evidence from one governed CN cloud snapshot."""

    return tuple(
        observer.ingest(observation)
        for observation in build_cn_provider_observations_from_cloud_snapshot(payload)
    )


_ALPACA_FEEDS = frozenset({
    "iex",
    "sip",
    "delayed_sip",
    "boats",
    "overnight",
    "otc",
})
_ALPACA_EVENT_TYPES = frozenset({
    "subscription_error",
    "subscription_registered",
    "stream_worker_started",
    "stream_worker_error",
    "worker_terminated",
    "stop_requested",
    "shutdown_failed",
    "owner_retained",
    "stream_stop_requested",
    "shutdown_completed",
    "owner_cleared",
})
_ALPACA_NEGATIVE_EVENT_TYPES = frozenset({
    "subscription_error",
    "stream_worker_error",
    "shutdown_failed",
    "owner_retained",
})
_ALPACA_WORKER_STATUSES = frozenset({
    "NOT_STARTED",
    "RUNNING",
    "FAILED",
    "TERMINATED",
})
_ALPACA_SHUTDOWN_STATUSES = frozenset({
    "REQUESTED",
    "FAILED",
    "SUCCEEDED",
})
_ALPACA_OWNER_STATUSES = frozenset({
    "RETAINED",
    "CLEARED",
})
_ALPACA_UNSUBSCRIBE_STATUSES = frozenset({
    "UNKNOWN",
})


def build_alpaca_observation_from_runtime_events(
    events: Sequence[Mapping[str, object]],
    *,
    repo_sha: str,
) -> ProviderRuntimeObservation:
    """Translate one Alpaca adapter instance's lifecycle events.

    Adapter registration and worker-thread liveness are deliberately not auth,
    readiness, entitlement, or Data Admission evidence. This source may emit
    UNKNOWN or negative lifecycle state only.
    """

    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        raise ProviderRuntimeIngestError("Alpaca runtime events must be a sequence")
    if not events:
        raise ProviderRuntimeIngestError("Alpaca runtime events must not be empty")

    exact_repo_sha = _exact_sha(repo_sha)
    normalized: list[dict[str, object]] = []
    owner_identity: str | None = None
    feed: str | None = None
    previous_at: datetime | None = None
    previous_generation = -1

    for index, raw_event in enumerate(events):
        event = _required_mapping(raw_event, f"events[{index}]")
        if event.get("provider_type") != "alpaca":
            raise ProviderRuntimeIngestError(
                f"events[{index}].provider_type must be alpaca"
            )
        event_type = _text(event.get("event_type"), f"events[{index}].event_type")
        if event_type not in _ALPACA_EVENT_TYPES:
            raise ProviderRuntimeIngestError(
                f"unsupported Alpaca event_type: {event_type}"
            )

        event_at = _parse_aware_timestamp(
            event.get("event_at"),
            f"events[{index}].event_at",
        )
        if previous_at is not None and event_at < previous_at:
            raise ProviderRuntimeIngestError(
                "Alpaca runtime event_at values must be non-decreasing"
            )
        previous_at = event_at

        current_owner = _text(
            event.get("owner_identity"),
            f"events[{index}].owner_identity",
        )
        if owner_identity is None:
            owner_identity = current_owner
        elif current_owner != owner_identity:
            raise ProviderRuntimeIngestError(
                "Alpaca runtime events must belong to one owner_identity"
            )

        current_feed = _text(event.get("feed"), f"events[{index}].feed").lower()
        if current_feed not in _ALPACA_FEEDS:
            raise ProviderRuntimeIngestError(
                f"unsupported Alpaca feed: {current_feed}"
            )
        if feed is None:
            feed = current_feed
        elif current_feed != feed:
            raise ProviderRuntimeIngestError(
                "Alpaca runtime events must use one feed"
            )

        generation = _nonnegative_int(
            event.get("runtime_generation"),
            f"events[{index}].runtime_generation",
        )
        if generation < previous_generation:
            raise ProviderRuntimeIngestError(
                "Alpaca runtime_generation must be non-decreasing"
            )
        previous_generation = generation

        if event.get("ack_status") != "UNKNOWN":
            raise ProviderRuntimeIngestError(
                "Alpaca adapter events cannot promote ack_status beyond UNKNOWN"
            )
        if event.get("ack_evidence") != "SDK_registration_return_only":
            raise ProviderRuntimeIngestError(
                "unexpected Alpaca ack_evidence source"
            )
        if event.get("entitlement_status") != "UNKNOWN":
            raise ProviderRuntimeIngestError(
                "Alpaca adapter events cannot prove entitlement"
            )
        if event.get("entitlement_source") != "EXTERNAL_ACCOUNT_EVIDENCE_REQUIRED":
            raise ProviderRuntimeIngestError(
                "unexpected Alpaca entitlement_source"
            )

        worker_status = _optional_exact_text(
            event.get("worker_status"),
            f"events[{index}].worker_status",
        )
        shutdown_status = _optional_exact_text(
            event.get("shutdown_status"),
            f"events[{index}].shutdown_status",
        )
        owner_status = _optional_exact_text(
            event.get("owner_status"),
            f"events[{index}].owner_status",
        )
        unsubscribe_status = _optional_exact_text(
            event.get("unsubscribe_status"),
            f"events[{index}].unsubscribe_status",
        )
        stream_error_type = _optional_exact_text(
            event.get("stream_error_type"),
            f"events[{index}].stream_error_type",
        )
        symbols = _string_tuple(event.get("symbols"), f"events[{index}].symbols")

        for field_name, value, allowed in (
            ("worker_status", worker_status, _ALPACA_WORKER_STATUSES),
            ("shutdown_status", shutdown_status, _ALPACA_SHUTDOWN_STATUSES),
            ("owner_status", owner_status, _ALPACA_OWNER_STATUSES),
            (
                "unsubscribe_status",
                unsubscribe_status,
                _ALPACA_UNSUBSCRIBE_STATUSES,
            ),
        ):
            if value is not None and value not in allowed:
                raise ProviderRuntimeIngestError(
                    f"events[{index}].{field_name} has unsupported value: {value}"
                )

        normalized.append({
            "event_type": event_type,
            "event_at": event_at,
            "runtime_generation": generation,
            "worker_status": worker_status,
            "shutdown_status": shutdown_status,
            "owner_status": owner_status,
            "unsubscribe_status": unsubscribe_status,
            "stream_error_type": stream_error_type,
            "symbols": symbols,
        })

    assert owner_identity is not None
    assert feed is not None
    latest = normalized[-1]
    latest_at = latest["event_at"]
    latest_generation = int(latest["runtime_generation"])

    last_failure: dict[str, object] | None = None
    current_negative: dict[str, object] | None = None
    for event in normalized:
        event_type = str(event["event_type"])
        if event_type in _ALPACA_NEGATIVE_EVENT_TYPES:
            last_failure = event
            current_negative = event
        elif event_type in {
            "shutdown_completed",
            "owner_cleared",
        }:
            current_negative = None
        # Registration, worker start, stop requests, and worker termination do
        # not prove recovery from a previously observed runtime failure.

    health_state = (
        ProviderHealthState.DEGRADED
        if current_negative is not None
        else ProviderHealthState.UNKNOWN
    )

    def event_failure_reason(event: Mapping[str, object]) -> str:
        event_type = str(event.get("event_type") or "UNKNOWN").upper()
        error_type = event.get("stream_error_type")
        if error_type is None:
            return f"ALPACA_{event_type}"[:240]
        safe_error = _text(error_type, "stream_error_type")
        return f"ALPACA_{event_type}:{safe_error}"[:240]

    current_failure_reason = (
        event_failure_reason(current_negative)
        if current_negative is not None
        else None
    )
    current_error_code = (
        str(current_negative["event_type"]).upper()
        if current_negative is not None
        else None
    )

    capabilities = MappingProxyType({
        "provider_type": "alpaca",
        "feed": feed,
        "event_count": len(normalized),
        "latest_event_type": latest["event_type"],
        "runtime_generation": latest_generation,
        "ack_status": "UNKNOWN",
        "ack_evidence": "SDK_registration_return_only",
        "entitlement_status": "UNKNOWN",
        "entitlement_source": "EXTERNAL_ACCOUNT_EVIDENCE_REQUIRED",
        "worker_status": latest.get("worker_status"),
        "shutdown_status": latest.get("shutdown_status"),
        "owner_status": latest.get("owner_status"),
        "unsubscribe_status": latest.get("unsubscribe_status"),
        "event_types": tuple(str(event["event_type"]) for event in normalized),
        "data_admission": "NOT_EVALUATED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    })

    def observed(
        field_name: str,
        value: object,
        *,
        observed_at: datetime = latest_at,
        error_code: str | None = current_error_code,
        evidence_suffix: str | None = None,
    ) -> ObservedProviderValue:
        suffix = evidence_suffix or f"{latest_generation}:{field_name}"
        return ObservedProviderValue(
            value=value,
            provenance=EvidenceProvenance(
                observed_at=observed_at,
                source="alpaca_adapter_runtime_events",
                runtime_id=owner_identity,
                repo_sha=exact_repo_sha,
                error_code=error_code,
                evidence_id=f"alpaca:{owner_identity}:{suffix}",
            ),
        )

    fields: dict[str, ObservedProviderValue] = {
        "health_state": observed("health_state", health_state),
        "failure_reason": observed(
            "failure_reason",
            current_failure_reason,
        ),
        "capabilities": observed(
            "capabilities",
            capabilities,
            error_code=None,
        ),
    }

    if last_failure is not None:
        failure_at = last_failure["event_at"]
        failure_type = str(last_failure["event_type"]).upper()
        fields["last_failure"] = observed(
            "last_failure",
            failure_at,
            observed_at=failure_at,
            error_code=failure_type,
            evidence_suffix=f"{last_failure['runtime_generation']}:last_failure",
        )

    return ProviderRuntimeObservation(
        provider_id="alpaca",
        fields=fields,
    )


def ingest_alpaca_runtime_events(
    observer: ProviderRuntimeObserver,
    events: Sequence[Mapping[str, object]],
    *,
    repo_sha: str,
) -> RuntimeProviderSnapshot:
    """Ingest one coherent Alpaca adapter event stream into lifecycle evidence."""

    return observer.ingest(
        build_alpaca_observation_from_runtime_events(
            events,
            repo_sha=repo_sha,
        )
    )


_NEGATIVE_PROBE_SCHEMA = "stock_razor_provider_negative_probe_v1"
_NEGATIVE_PROBE_PROVIDERS = frozenset({
    "openai",
    "anthropic",
    "tavily",
    "twelve_data",
    "eodhd",
    "aws",
})
_NEGATIVE_PROBE_CONDITIONS = frozenset({
    "AUTH_FAILED",
    "EXPIRED_OR_INVALID",
    "INSUFFICIENT_QUOTA",
    "CREDIT_BALANCE_EXHAUSTED",
    "RATE_LIMITED",
    "PROVIDER_FAILED",
})
_FORBIDDEN_NEGATIVE_PROBE_KEYS = frozenset({
    "api_key",
    "authorization",
    "headers",
    "request_headers",
    "response_body",
    "raw_response",
    "error_message",
    "message",
    "detail",
})
_NEGATIVE_PROBE_ALLOWED_KEYS = frozenset({
    "schema",
    "provider_id",
    "condition",
    "observed_at_utc",
    "runtime_instance_id",
    "repo_sha",
    "probe_source",
    "http_status",
    "error_code",
    "error_type",
    "research_only",
    "radar_admission",
    "live_trade",
})


def _optional_http_status(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ProviderRuntimeIngestError("http_status must be an integer")
    if value < 100 or value > 599:
        raise ProviderRuntimeIngestError("http_status must be between 100 and 599")
    return value


def _safe_probe_token(
    value: object,
    field_name: str,
    *,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise ProviderRuntimeIngestError(f"{field_name} is required")
        return None
    token = _text(value, field_name)
    if len(token) > 80:
        raise ProviderRuntimeIngestError(
            f"{field_name} must not exceed 80 characters"
        )
    if any(
        not (character.isalnum() or character in "._:-")
        for character in token
    ):
        raise ProviderRuntimeIngestError(
            f"{field_name} must be a sanitized token"
        )
    return token


def build_negative_provider_probe_observation(
    payload: Mapping[str, object],
) -> ProviderRuntimeObservation:
    """Translate one sanitized negative provider probe into lifecycle evidence.

    This contract is intentionally negative-only. It cannot prove HEALTHY,
    credential validity, quota headroom, Data Admission, Radar Admission, or
    execution readiness.
    """

    if not isinstance(payload, Mapping):
        raise ProviderRuntimeIngestError("negative provider probe must be a mapping")
    if payload.get("schema") != _NEGATIVE_PROBE_SCHEMA:
        raise ProviderRuntimeIngestError("unexpected negative provider probe schema")

    invalid_keys = [key for key in payload if not isinstance(key, str)]
    if invalid_keys:
        raise ProviderRuntimeIngestError(
            "negative provider probe field names must be strings"
        )

    forbidden_present = sorted(
        key
        for key in payload
        if key.lower() in _FORBIDDEN_NEGATIVE_PROBE_KEYS
    )
    if forbidden_present:
        raise ProviderRuntimeIngestError(
            "negative provider probe contains forbidden raw/sensitive field(s): "
            + ", ".join(forbidden_present)
        )

    unknown_keys = sorted(set(payload) - _NEGATIVE_PROBE_ALLOWED_KEYS)
    if unknown_keys:
        raise ProviderRuntimeIngestError(
            "negative provider probe contains unsupported field(s): "
            + ", ".join(unknown_keys)
        )

    if payload.get("research_only") is not True:
        raise ProviderRuntimeIngestError(
            "negative provider probe must remain research_only"
        )
    if payload.get("radar_admission") != "BLOCKED":
        raise ProviderRuntimeIngestError(
            "negative provider probe must preserve RADAR_ADMISSION=BLOCKED"
        )
    if payload.get("live_trade") is not False:
        raise ProviderRuntimeIngestError(
            "negative provider probe must preserve LIVE_TRADE=NO"
        )

    provider_id = _text(payload.get("provider_id"), "provider_id")
    if provider_id != provider_id.lower():
        raise ProviderRuntimeIngestError("provider_id must be lowercase")
    if provider_id not in _NEGATIVE_PROBE_PROVIDERS:
        raise ProviderRuntimeIngestError(
            f"provider_id is not eligible for generic negative probe ingest: {provider_id}"
        )

    runtime_id = _safe_probe_token(
        payload.get("runtime_instance_id"),
        "runtime_instance_id",
        required=True,
    )
    assert runtime_id is not None
    repo_sha = _exact_sha(payload.get("repo_sha"))
    observed_at = _parse_aware_timestamp(
        payload.get("observed_at_utc"),
        "observed_at_utc",
    )
    probe_source = _safe_probe_token(
        payload.get("probe_source"),
        "probe_source",
        required=True,
    )
    assert probe_source is not None
    if probe_source != probe_source.lower():
        raise ProviderRuntimeIngestError("probe_source must be lowercase")
    condition = _text(payload.get("condition"), "condition").upper()
    if condition not in _NEGATIVE_PROBE_CONDITIONS:
        raise ProviderRuntimeIngestError(
            f"unsupported negative provider condition: {condition}"
        )

    http_status = _optional_http_status(payload.get("http_status"))
    error_code = _safe_probe_token(payload.get("error_code"), "error_code")
    error_type = _safe_probe_token(payload.get("error_type"), "error_type")

    credential_status: str | None = None
    billing_status: str | None = None
    if condition == "AUTH_FAILED":
        health_state = ProviderHealthState.FAILED
        credential_status = "AUTH_FAILED"
    elif condition == "EXPIRED_OR_INVALID":
        health_state = ProviderHealthState.EXPIRED
        credential_status = "EXPIRED_OR_INVALID"
    elif condition == "INSUFFICIENT_QUOTA":
        health_state = ProviderHealthState.EXHAUSTED
        billing_status = "INSUFFICIENT_QUOTA"
    elif condition == "CREDIT_BALANCE_EXHAUSTED":
        health_state = ProviderHealthState.EXHAUSTED
        billing_status = "CREDIT_BALANCE_EXHAUSTED"
    elif condition == "RATE_LIMITED":
        health_state = ProviderHealthState.RATE_LIMITED
    else:
        health_state = ProviderHealthState.FAILED

    reason_parts = [condition]
    if error_code is not None:
        reason_parts.append(f"CODE={error_code}")
    if error_type is not None:
        reason_parts.append(f"TYPE={error_type}")
    if http_status is not None:
        reason_parts.append(f"HTTP={http_status}")
    failure_reason = "|".join(reason_parts)[:240]

    capabilities = MappingProxyType({
        "negative_probe_schema": _NEGATIVE_PROBE_SCHEMA,
        "negative_evidence_only": True,
        "probe_source": probe_source,
        "condition": condition,
        "http_status": http_status,
        "error_code": error_code,
        "error_type": error_type,
        "research_only": True,
        "data_admission": "NOT_EVALUATED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    })

    def observed(
        field_name: str,
        value: object,
    ) -> ObservedProviderValue:
        return ObservedProviderValue(
            value=value,
            provenance=EvidenceProvenance(
                observed_at=observed_at,
                source=f"provider_negative_probe:{probe_source}",
                runtime_id=runtime_id,
                repo_sha=repo_sha,
                error_code=condition,
                evidence_id=(
                    f"provider-negative:{provider_id}:{runtime_id}:"
                    f"{observed_at.isoformat()}:{field_name}"
                ),
            ),
        )

    fields: dict[str, ObservedProviderValue] = {
        "health_state": observed("health_state", health_state),
        "last_failure": observed("last_failure", observed_at),
        "failure_reason": observed("failure_reason", failure_reason),
        "capabilities": observed("capabilities", capabilities),
    }
    if credential_status is not None:
        fields["credential_status"] = observed(
            "credential_status",
            credential_status,
        )
    if billing_status is not None:
        fields["billing_status"] = observed(
            "billing_status",
            billing_status,
        )

    return ProviderRuntimeObservation(
        provider_id=provider_id,
        fields=fields,
    )


def ingest_negative_provider_probe(
    observer: ProviderRuntimeObserver,
    payload: Mapping[str, object],
) -> RuntimeProviderSnapshot:
    """Ingest one sanitized negative provider probe."""

    return observer.ingest(
        build_negative_provider_probe_observation(payload)
    )

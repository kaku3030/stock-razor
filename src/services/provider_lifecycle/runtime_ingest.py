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

    runtime_id = _text(payload.get("runtime_instance_id"), "runtime_instance_id")
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
                if str(frame.get("currentness") or "UNPROVEN").strip().upper() == "PROVEN":
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
        "intraday_timestamp_semantics_proven": bool(
            payload.get("intraday_timestamp_semantics_proven") is True
        ),
        "intraday_currentness_proven": bool(
            payload.get("intraday_currentness_proven") is True
        ),
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

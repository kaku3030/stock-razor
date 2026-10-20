from __future__ import annotations

import os

from fastapi import APIRouter

from api.v1.schemas.operations import (
    OperationsStatusResponse,
    PaperOperatorAction,
    PaperOperatorControlsResponse,
    USLiveMonitorResponse,
)
from data_provider.us_canonical_runtime_reader import (
    read_us_livefeed_health,
    read_us_market_snapshots,
)
from src.notification_routing import NOTIFICATION_ROUTE_CONFIGS, split_notification_route_channels
from src.services.execution_engine import ExecutionBlocked
from src.services.paper_runtime_store_config import PaperRuntimeStoreConfig

router = APIRouter()


_CHANNEL_ENV = {
    "discord": ("DISCORD_WEBHOOK_URL",),
    "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
    "wechat": ("WECHAT_WEBHOOK_URL",),
    "feishu": ("FEISHU_WEBHOOK_URL", "FEISHU_APP_ID"),
    "dingtalk": ("DINGTALK_WEBHOOK_URL",),
    "pushover": ("PUSHOVER_USER_KEY", "PUSHOVER_API_TOKEN"),
    "ntfy": ("NTFY_TOPIC",),
    "gotify": ("GOTIFY_URL", "GOTIFY_TOKEN"),
    "pushplus": ("PUSHPLUS_TOKEN",),
    "serverchan3": ("SERVERCHAN3_SENDKEY",),
}


def _configured_channels() -> list[str]:
    channels: list[str] = []
    for channel, keys in _CHANNEL_ENV.items():
        if all(os.getenv(key, "").strip() for key in keys):
            channels.append(channel)
    # Radar alerts may intentionally use a dedicated Discord webhook while
    # report notifications keep the legacy webhook. Either route means the
    # Discord notification surface is configured, but this is not delivery
    # proof; the UI still asks for a real phone receipt.
    if os.getenv("DISCORD_RADAR_WEBHOOK_URL", "").strip() and "discord" not in channels:
        channels.append("discord")
    return channels


def _paper_runtime_store_config_status() -> str:
    try:
        return PaperRuntimeStoreConfig.from_env().status()
    except ExecutionBlocked:
        return "NOT_CONFIGURED_OR_INVALID"


def _effective_notification_routes(channels: list[str]) -> dict[str, list[str]]:
    """Expose effective route targets without exposing secrets or send proofs."""

    configured = set(channels)
    routes: dict[str, list[str]] = {}
    for route_type, route_config in NOTIFICATION_ROUTE_CONFIGS.items():
        raw = os.getenv(route_config["env_key"], "").strip()
        if not raw:
            routes[route_type] = list(channels)
            continue
        valid, _invalid = split_notification_route_channels(raw)
        routes[route_type] = [channel for channel in valid if channel in configured]
    return routes


def _monitor_projection(payload: dict, allowed_fields: set[str]) -> dict:
    """Project runtime data onto the public monitor contract."""

    return {key: value for key, value in payload.items() if key in allowed_fields}


_MONITOR_HEALTH_FIELDS = {
    "ok", "status", "heartbeat_age_seconds", "repo_sha", "runtime_instance_id",
    "sequence", "emitted_at_utc", "controller_lifecycle", "market_state_us",
    "cache_session_us", "delivery_mode", "bar_closure", "provider_callback_latency_ms",
    "provider_callback_latency_sample_count", "realtime_delivery_evidence",
    "realtime_evidence_scope", "bar_closure_proven", "read_latency_ms",
    "last_push_utc", "last_push_age_seconds", "latest_push_status",
    "latest_push_observations", "radar_admission", "live_trade",
}
_MONITOR_MARKET_FIELDS = {
    "ok", "status", "source_age_seconds", "publication_age_seconds", "repo_sha",
    "runtime_instance_id", "sequence", "emitted_at_utc", "latest_source_timestamp_utc",
    "latest_received_at_utc", "market_state_us", "cache_session_us", "delivery_mode",
    "bar_closure", "missing_symbols", "data_available", "read_latency_ms",
    "radar_admission", "live_trade",
}
_MONITOR_BAR_FIELDS = {
    "bar_start_utc", "bar_end_utc", "open", "high", "low", "close", "volume",
    "amount", "source_timestamp_utc", "received_at_utc", "session", "is_closed",
    "is_complete", "provider", "feed", "latency_ms", "freshness_ms", "quality_flags",
    "fallback_from",
}
_MONITOR_QUALITY_FIELDS = {"grade", "quality_flags"}


def _monitor_market_projection(payload: dict) -> dict:
    result = _monitor_projection(payload, _MONITOR_MARKET_FIELDS)
    source_symbols = payload.get("symbols")
    projected_symbols = {}
    if isinstance(source_symbols, dict):
        for symbol, item in source_symbols.items():
            if not isinstance(item, dict):
                continue
            projected = {
                key: item[key]
                for key in ("provider", "feed", "counts")
                if key in item
            }
            latest = item.get("latest")
            if isinstance(latest, dict):
                frames = {}
                for timeframe in ("1m", "5m", "15m", "1h"):
                    bar = latest.get(timeframe)
                    if not isinstance(bar, dict):
                        frames[timeframe] = None
                        continue
                    bar_data = _monitor_projection(bar, _MONITOR_BAR_FIELDS)
                    quality = bar.get("health")
                    if isinstance(quality, dict):
                        bar_data["health"] = _monitor_projection(
                            quality, _MONITOR_QUALITY_FIELDS
                        )
                    frames[timeframe] = bar_data
                projected["latest"] = frames
            projected_symbols[symbol] = projected
    result["symbols"] = projected_symbols
    return result


def _monitor_health_projection(payload: dict) -> dict:
    result = _monitor_projection(payload, _MONITOR_HEALTH_FIELDS)
    source = payload.get("latest_push_observations")
    observations = {}
    allowed = {
        "symbol", "time_key", "received_at_utc", "open", "high", "low",
        "close", "volume", "age_seconds", "freshness_status", "bar_closure",
        "research_eligible",
    }
    if isinstance(source, dict):
        for symbol, item in source.items():
            if isinstance(item, dict):
                observations[symbol] = _monitor_projection(item, allowed)
    result["latest_push_observations"] = observations
    return result


@router.get("/status", response_model=OperationsStatusResponse)
def operations_status() -> OperationsStatusResponse:
    """Expose safety and notification readiness without mutating runtime state."""

    # These fields are effective, qualified admissions, not raw operator
    # requests from environment variables. Until a verified source arbiter
    # and Radar admission proof is wired to this read-only surface, an
    # environment typo or "PASS" value must NEVER claim admission.
    channels = _configured_channels()
    pending = [
        "TickFlow 实盘连续性与真实历史交叉验证",
        "真实手机接收回执",
        "PAPER_AUTO_READY 独立验收",
        "云端 OpenD SIMULATE 账户只读发现",
    ]
    return OperationsStatusResponse(
        # This surface is offline-only with no authorized external Paper operator.
        # Do not present PAPER mode because env flags happen to say PASS.
        mode="research_only",
        radar_admission="BLOCKED",
        source_arbiter_admission="BLOCKED",
        # This endpoint intentionally cannot unlock live trading.
        live_trade=False,
        # An environment toggle cannot substitute for independently verified
        # broker/account/position/order evidence and an exposed operator.
        paper_auto_ready=False,
        paper_engine_status="IMPLEMENTED_OFFLINE_ONLY",
        offline_simulation_status="READY_EXPLICIT_OFFLINE_RUN_EXTERNAL_BROKER_NOT_CONNECTED",
        paper_runtime_api_status="NOT_EXPOSED",
        execution_recovery_projection_status="IMPLEMENTED_READ_ONLY_RUNTIME_WIRING_PENDING",
        paper_runtime_store_config_status=_paper_runtime_store_config_status(),
        trade_plan_status="IMPLEMENTED_READ_ONLY_V0_2",
        position_management_status="IMPLEMENTED_READ_ONLY_V0_1",
        trade_lifecycle_status="IMPLEMENTED_READ_ONLY_V0_3_RUNTIME_WIRING_PENDING",
        external_simulator_contract_status="READY_READ_ONLY_UNVERIFIED_CLOUD_ACCOUNT",
        simulated_account_evidence="NOT_VERIFIED",
        notification_channels_configured=channels,
        notification_routes=_effective_notification_routes(channels),
        notification_delivery_evidence="NOT_VERIFIED",
        # Configured channel credentials are not a real phone receipt.
        # Keep effective readiness BLOCKED until a separately authenticated
        # end-to-end delivery receipt is consumed by the notification owner.
        notification_ready=False,
        pending_acceptance=pending,
    )


@router.get("/us-live-monitor", response_model=USLiveMonitorResponse)
def us_live_monitor(symbols: str = "US.AMD,US.QQQ") -> USLiveMonitorResponse:
    """Expose bounded OpenD cache evidence; never contacts a broker/provider."""

    requested = [item.strip() for item in symbols.split(",") if item.strip()]
    if not requested or len(requested) > 20:
        requested = []
    health = read_us_livefeed_health()
    market = read_us_market_snapshots(requested or ["__invalid__"])
    source_identity_matched = bool(
        health.get("repo_sha")
        and health.get("runtime_instance_id")
        and health.get("repo_sha") == market.get("repo_sha")
        and health.get("runtime_instance_id") == market.get("runtime_instance_id")
    )
    health_sequence = health.get("sequence")
    market_sequence = market.get("sequence")
    source_sequence_matched = (
        type(health_sequence) is int
        and health_sequence > 0
        and type(market_sequence) is int
        and market_sequence > 0
        and health_sequence == market_sequence
    )
    source_evidence = (
        health.get("realtime_delivery_evidence") is True
        and market.get("status") == "PASS"
        and market.get("data_available") is True
        and source_identity_matched
        and source_sequence_matched
    )
    status = "REALTIME_SOURCE_EVIDENCE" if source_evidence else "BLOCKED_OR_STALE"
    return USLiveMonitorResponse(
        source="CLOUD_CANONICAL_OPEND_CACHE",
        status=status,
        source_identity_matched=source_identity_matched,
        source_sequence_matched=source_sequence_matched,
        health=_monitor_health_projection(health),
        market=_monitor_market_projection(market),
        radar_admission="BLOCKED",
        live_trade=False,
    )



@router.get("/paper-controls", response_model=PaperOperatorControlsResponse)
def paper_operator_controls() -> PaperOperatorControlsResponse:
    """Expose operator capability boundaries; never activate Paper from HTTP.

    This deliberately ignores permissive environment variables: an operator
    read must not turn a deployment typo into execution permission.  A future
    command endpoint requires separate identity, authorization, CSRF/replay
    protection, account reconciliation and review.
    """

    return PaperOperatorControlsResponse(
        actions=[
            PaperOperatorAction(
                action="inspect_operator_controls",
                available=True,
                reason="READ_ONLY_NO_SIDE_EFFECTS",
            ),
            PaperOperatorAction(
                action="run_offline_simulation",
                reason="LIBRARY_ONLY_EXPLICIT_INPUT_NO_HTTP_TRIGGER",
            ),
            PaperOperatorAction(
                action="discover_external_paper_account",
                reason="CLOUD_ACCOUNT_IDENTITY_NOT_VERIFIED",
            ),
            PaperOperatorAction(
                action="submit_external_paper_order",
                reason="NO_AUTHORIZED_OPERATOR_OR_VERIFIED_ACCOUNT",
            ),
            PaperOperatorAction(
                action="cancel_or_replace_external_paper_order",
                reason="NO_AUTHORIZED_OPERATOR_OR_VERIFIED_ACCOUNT",
            ),
            PaperOperatorAction(
                action="send_phone_alert",
                reason="NO_VERIFIED_PHONE_RECEIPT_OR_SEND_APPROVAL",
            ),
        ]
    )

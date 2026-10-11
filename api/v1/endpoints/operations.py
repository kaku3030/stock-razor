from __future__ import annotations

import os

from fastapi import APIRouter

from api.v1.schemas.operations import (
    OperationsStatusResponse,
    PaperOperatorAction,
    PaperOperatorControlsResponse,
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


@router.get("/status", response_model=OperationsStatusResponse)
def operations_status() -> OperationsStatusResponse:
    """Expose safety and notification readiness without mutating runtime state."""

    radar = os.getenv("RADAR_ADMISSION", "BLOCKED").strip().upper() or "BLOCKED"
    arbiter = os.getenv("SOURCE_ARBITER_ADMISSION", "BLOCKED").strip().upper() or "BLOCKED"
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
        radar_admission=radar,
        source_arbiter_admission=arbiter,
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
        notification_ready=bool(channels),
        pending_acceptance=pending,
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

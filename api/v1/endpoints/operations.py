from __future__ import annotations

import os

from fastapi import APIRouter

from api.v1.schemas.operations import OperationsStatusResponse

router = APIRouter()


_CHANNEL_ENV = {
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
    return channels


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
    ]
    return OperationsStatusResponse(
        mode="research_only" if radar != "PASS" or arbiter != "PASS" else "paper_only",
        radar_admission=radar,
        source_arbiter_admission=arbiter,
        # This endpoint intentionally cannot unlock live trading.
        live_trade=False,
        paper_auto_ready=os.getenv("PAPER_AUTO_READY", "NO").strip().upper() == "YES",
        notification_channels_configured=channels,
        notification_ready=bool(channels),
        pending_acceptance=pending,
    )


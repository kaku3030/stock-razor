"""Production notification sink for Stock Radar V2 research events."""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from .notifications import RadarNotification


EVENT_LABELS = {
    "data_health_alert": "行情数据健康告警",
    "provider_fallback_alert": "行情源切换告警",
    "signal_qa_alert": "信号质量复核告警",
    "portfolio_risk_alert": "组合风险门禁告警",
    "confirmed_signal_alert": "已确认研究信号提醒",
}
logger = logging.getLogger(__name__)

# Only research/status metadata may leave this sink. Upstream event payloads
# can contain full provider errors, URLs, broker metadata or even credentials.
# These fields are deliberately finite until each additional field is audited.
_PUBLIC_FIELDS = frozenset({
    "provider", "from", "level", "severity", "signal_type", "signal_id",
    "review_id", "failure_count", "reason", "risk_gate", "signal_state",
    "status", "symbol", "code", "timeframe", "session_state",
    "data_quality", "source_revision", "observed_at_utc", "error_code",
})
_MAX_TEXT_BYTES = 160
_SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|token|authorization|cookie|secret|password|"
    r"credential|account[_-]?id|session[_-]?id|access[_-]?key|"
    r"https?://|(?:sk|ghp|gho|github_pat|xoxb)[_-][a-z0-9_-]{10,})"
)


def _public_payload(payload: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """Project only bounded, scalar, non-sensitive research metadata."""
    safe: dict[str, str | int | float | bool] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or key not in _PUBLIC_FIELDS:
            continue
        if isinstance(value, bool):
            safe[key] = value
        elif type(value) is int:
            safe[key] = value
        elif type(value) is float:
            if math.isfinite(value):
                safe[key] = value
        elif isinstance(value, str):
            if (
                len(value.encode("utf-8")) > _MAX_TEXT_BYTES
                or "\n" in value or "\r" in value
                or _SECRET_PATTERN.search(value)
            ):
                safe[key] = "[REDACTED]"
            elif value:
                safe[key] = value
        # Nested data, arbitrary objects and bytes are intentionally dropped.
    return safe


class NotificationServiceRadarSink:
    """Send typed radar events through the repository's existing channels."""

    def __init__(self, service: Any | None = None) -> None:
        if service is None:
            from src.notification import get_notification_service

            service = get_notification_service()
        self._service = service
        self.last_dispatch: Any | None = None
        self.last_error: str | None = None

    def __call__(self, event: RadarNotification) -> None:
        payload = _public_payload(dict(event.payload))
        severity = _severity(event.event_type, payload)
        content = format_radar_notification(event)
        identity = _event_identity(event.event_type, payload)
        dedup_key = f"stock_radar_v2:{event.event_type}:{identity}:{_event_state(payload)}"
        cooldown_key = f"stock_radar_v2:{event.event_type}:{identity}:{severity}"
        try:
            self.last_dispatch = self._service.send_with_results(
                content,
                route_type="alert",
                severity=severity,
                dedup_key=dedup_key,
                cooldown_key=cooldown_key,
                structured_payload={
                    "event_type": event.event_type,
                    "research_only": True,
                    "payload": payload,
                },
            )
            self.last_error = None
        except Exception as exc:
            # A channel exception can embed a webhook URL or access token.
            self.last_error = type(exc).__name__
            logger.warning("Stock Radar notification dispatch failed: %s", type(exc).__name__)


def format_radar_notification(event: RadarNotification) -> str:
    payload = _public_payload(dict(event.payload))
    lines = [
        f"⚠️ **Stock Radar V2：{EVENT_LABELS[event.event_type]}**",
        "",
    ]
    for key, value in payload.items():
        if value in (None, "", [], {}):
            continue
        label = str(key).replace("_", " ")
        lines.append(f"- {label}: {value}")
    lines.extend(
        [
            "",
            "> 这是数据质量与研究流程提醒，不是买卖建议或交易指令。",
        ]
    )
    return "\n".join(lines)


def _severity(event_type: str, payload: dict[str, Any]) -> str:
    explicit = str(payload.get("severity") or "").lower()
    if explicit in {"critical", "warning", "info"}:
        return explicit
    if event_type in {"data_health_alert", "portfolio_risk_alert"}:
        return "critical"
    if event_type in {"provider_fallback_alert", "signal_qa_alert"}:
        return "warning"
    return "info"


def _event_identity(event_type: str, payload: dict[str, Any]) -> str:
    if event_type == "signal_qa_alert":
        return str(payload.get("signal_type") or "global")
    return str(
        payload.get("signal_id")
        or payload.get("provider")
        or payload.get("from")
        or payload.get("level")
        or "global"
    )


def _event_state(payload: dict[str, Any]) -> str:
    return str(
        payload.get("reason")
        or payload.get("risk_gate")
        or payload.get("failure_count")
        or payload.get("signal_state")
        or "observed"
    )

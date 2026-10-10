from __future__ import annotations

from pydantic import BaseModel, Field


class OperationsStatusResponse(BaseModel):
    """Read-only runtime gates used by the operations console."""

    mode: str = Field(description="Effective safety mode")
    radar_admission: str
    source_arbiter_admission: str
    live_trade: bool
    paper_auto_ready: bool
    notification_channels_configured: list[str]
    notification_ready: bool
    pending_acceptance: list[str]


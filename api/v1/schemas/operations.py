from __future__ import annotations

from pydantic import BaseModel, Field


class OperationsStatusResponse(BaseModel):
    """Read-only runtime gates used by the operations console."""

    mode: str = Field(description="Effective safety mode")
    radar_admission: str
    source_arbiter_admission: str
    live_trade: bool
    paper_auto_ready: bool
    paper_engine_status: str
    offline_simulation_status: str
    paper_runtime_api_status: str
    execution_recovery_projection_status: str
    paper_runtime_store_config_status: str
    trade_plan_status: str
    position_management_status: str
    trade_lifecycle_status: str
    external_simulator_contract_status: str
    simulated_account_evidence: str
    notification_channels_configured: list[str]
    notification_routes: dict[str, list[str]]
    notification_delivery_evidence: str
    notification_ready: bool
    pending_acceptance: list[str]


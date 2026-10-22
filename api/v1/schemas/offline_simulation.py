from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class OfflineSimulationRequest(BaseModel):
    """Explicit user-entered scenario; never sourced from a broker or provider."""

    symbol: str = Field(min_length=1, max_length=12)
    side: Literal["BUY", "SELL"] = "BUY"
    quantity: Decimal = Field(gt=0, le=1_000_000, max_digits=18, decimal_places=6)
    limit_price: Decimal = Field(gt=0, le=1_000_000, max_digits=18, decimal_places=6)
    max_slippage: Decimal = Field(default=Decimal("0.01"), ge=0, le=1, max_digits=8, decimal_places=6)
    simulate_fill: bool = False

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^" for ch in normalized):
            raise ValueError("symbol contains unsupported characters")
        return normalized


class OfflineSimulationResponse(BaseModel):
    scenario_id: str
    environment: Literal["LOCAL_OFFLINE_SIMULATION"] = "LOCAL_OFFLINE_SIMULATION"
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: str
    limit_price: str
    currency: Literal["USD", "CNY"]
    runtime_state: str
    order_state: str
    filled_quantity: str
    external_fill_confirmation: Literal[False] = False
    fill_source: Literal["LOCAL_SCENARIO_FIXTURE", "NONE"]
    broker_io: Literal[False] = False
    provider_io: Literal[False] = False
    live_trade: Literal[False] = False
    note: str = "User-entered local scenario only. It is not a real signal, broker order, account, or externally confirmed fill."

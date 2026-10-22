from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import re
import tempfile
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from api.v1.schemas.offline_simulation import (
    OfflineSimulationRequest,
    OfflineSimulationResponse,
)
from src.services.execution_engine import (
    ExecutionBlocked,
    RiskContext,
    RiskGuard,
    RiskLimits,
    Side,
    create_paper_adapter,
)
from src.services.offline_paper_simulation import run_offline_paper_simulation
from src.services.paper_execution_admission import PaperOrderSpec, build_paper_order_intent
from src.services.stock_radar_v2.observation_ledger import Observation

router = APIRouter()


@router.post("/offline-simulation", response_model=OfflineSimulationResponse)
def post_offline_simulation(request: OfflineSimulationRequest) -> OfflineSimulationResponse:
    return run_offline_simulation(request)


_CN_SYMBOL = re.compile(r"^\d{6}\.(SH|SZ)$")
_US_SYMBOL = re.compile(r"^[A-Z][A-Z0-9.\-^]{0,10}$")


def run_offline_simulation(
    request: OfflineSimulationRequest,
) -> OfflineSimulationResponse:
    """Run one explicit, synthetic scenario through the offline Paper engine."""

    symbol = request.symbol
    is_cn = bool(_CN_SYMBOL.fullmatch(symbol))
    if not is_cn and not _US_SYMBOL.fullmatch(symbol):
        raise HTTPException(status_code=422, detail="Use a US ticker or a six-digit .SH/.SZ symbol.")
    if request.side != "BUY":
        raise HTTPException(status_code=422, detail="Sell scenarios require a virtual position baseline and are not enabled in this release.")
    if is_cn and request.quantity % Decimal("100") != 0:
        raise HTTPException(status_code=422, detail="A-share scenario quantity must be a multiple of 100.")

    now = datetime.now(timezone.utc)
    scenario_id = uuid4().hex
    notional = request.quantity * request.limit_price
    evidence_id = f"manual-scenario-{scenario_id}"
    evidence = Observation(
        observation_id=evidence_id,
        detector_status="CONFIRMED",
        evidence_ids=(evidence_id,),
        strategy_gate_results={"scenario": "USER_ENTERED_SYNTHETIC"},
        strategy_eligible=True,
        portfolio_admissible=True,
        portfolio_block_reasons=(),
        execution_feasible=True,
        decision_available_at=now.timestamp() - 2,
        confirmed_at=now.timestamp() - 1,
        earliest_executable_at=now.timestamp() - 1,
        canonical_permission="PASS",
    )
    spec = PaperOrderSpec(
        action_id=scenario_id,
        symbol=symbol,
        side=Side(request.side),
        qty=request.quantity,
        limit_price=request.limit_price,
        max_slippage=request.max_slippage,
        strategy_id="manual-offline-scenario",
        evidence_snapshot_id=evidence_id,
        valid_until=now + timedelta(minutes=5),
    )
    intent = build_paper_order_intent(evidence, spec, now=now)
    fills = {intent.intent_id: ((f"scenario-fill-{scenario_id}", request.quantity, request.limit_price),)} if request.simulate_fill else None
    capability = create_paper_adapter(fills=fills)
    risk_guard = RiskGuard(
        RiskLimits(
            allowed_symbols=frozenset({symbol}),
            max_order_notional=notional,
            max_order_qty=request.quantity,
            max_symbol_exposure=notional,
            max_portfolio_exposure=notional,
            max_slippage=Decimal("1"),
            max_open_orders=1,
            data_ttl_seconds=60,
            account_ttl_seconds=60,
        )
    )

    try:
        # Isolated per-run stores are discarded after the response. No shared
        # Paper ledger, broker, provider, scheduler, or live runtime is touched.
        with tempfile.TemporaryDirectory(prefix="stock-razor-offline-sim-") as root:
            report = run_offline_paper_simulation(
                capability,
                risk_guard,
                evidence,
                spec,
                RiskContext(now=now, data_as_of=now, session="RTH"),
                root_path=root,
                runtime_generation=f"offline-{scenario_id}",
                account_generation=f"scenario-{scenario_id}",
            )
    except ExecutionBlocked as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return OfflineSimulationResponse(
        scenario_id=scenario_id,
        symbol=symbol,
        side=request.side,
        quantity=str(request.quantity),
        limit_price=str(request.limit_price),
        currency="CNY" if is_cn else "USD",
        runtime_state=report.runtime.state.value,
        order_state=report.result.order_state.value,
        filled_quantity=str(report.result.filled_qty),
        fill_source="LOCAL_SCENARIO_FIXTURE" if request.simulate_fill else "NONE",
    )

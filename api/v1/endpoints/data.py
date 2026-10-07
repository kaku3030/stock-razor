# -*- coding: utf-8 -*-
"""Data capability and fail-closed read-only market snapshot endpoints."""

from __future__ import annotations

import hmac
import logging
import os
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request

from api.deps import get_config_dep
from api.v1.schemas.common import ErrorResponse
from api.v1.schemas.data_capability import DataCapabilityOverviewResponse
from api.v1.schemas.market_snapshot import MarketSnapshotResponse
from src.auth import COOKIE_NAME, is_auth_enabled, verify_session
from src.config import Config
from src.services.data_capability_service import DataCapabilityService
from src.services.vti_market_data import VtiMarketDataService

logger = logging.getLogger(__name__)

router = APIRouter()

# This endpoint consumes an AI Monitor-owned snapshot service only. It must not
# instantiate a provider client, subscribe to streams, or reconcile controller
# state. The bearer token is separately configured in a secure environment.
_SYMBOL_RE = re.compile(r"^(?:[A-Z]{1,5}(?:\.[A-Z])?|\d{6})$")


def _require_vti_session(request: Request) -> None:
    """Require explicit admin auth for browser-facing VTI data.

    The legacy API may intentionally run with admin auth disabled. The VTI
    bridge does not inherit that permissive mode because it exposes market
    data intended for remote browser use. This endpoint therefore fails closed
    unless auth is enabled and the HttpOnly admin session is valid.
    """

    if not is_auth_enabled():
        raise HTTPException(
            status_code=503,
            detail="VTI market-data bridge requires admin authentication to be enabled",
        )
    cookie_val = request.cookies.get(COOKIE_NAME)
    if not cookie_val or not verify_session(cookie_val):
        raise HTTPException(status_code=401, detail="valid VTI admin session required")


def _overview_response(config: Config, *, runtime_scheduler: object = None) -> DataCapabilityOverviewResponse:
    try:
        payload = DataCapabilityService(
            config=config,
            runtime_scheduler=runtime_scheduler,
        ).get_overview()
        return DataCapabilityOverviewResponse.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - keep diagnostics fail-open at API boundary.
        logger.error("Failed to build data capability overview: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "internal_error",
                "message": "Failed to build data capability overview",
            },
        )


@router.get(
    "/overview",
    response_model=DataCapabilityOverviewResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get data capability overview",
    description="Return provider capabilities, dataset quality, and source priority without exposing secrets.",
)
def get_data_overview(
    request: Request,
    config: Config = Depends(get_config_dep),
) -> DataCapabilityOverviewResponse:
    """Return the canonical read-only data overview."""
    return _overview_response(
        config,
        runtime_scheduler=getattr(request.app.state, "runtime_scheduler_service", None),
    )


@router.get(
    "/capabilities",
    response_model=DataCapabilityOverviewResponse,
    responses={500: {"model": ErrorResponse}},
    summary="Get data provider capabilities",
    description="Alias of /data/overview for clients that only need capability metadata.",
)
def get_data_capabilities(
    request: Request,
    config: Config = Depends(get_config_dep),
) -> DataCapabilityOverviewResponse:
    """Return the data overview under the capability-oriented alias."""
    return _overview_response(
        config,
        runtime_scheduler=getattr(request.app.state, "runtime_scheduler_service", None),
    )


@router.get(
    "/market-snapshot/{symbol}",
    response_model=MarketSnapshotResponse,
    responses={401: {"description": "Authentication required"}, 503: {"description": "Runtime not ready"}},
    summary="Read an AI Monitor-owned market snapshot",
    description="Authenticated and read-only. Does not subscribe, mutate providers or infer realtime entitlement.",
)
def get_market_snapshot(
    symbol: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> MarketSnapshotResponse:
    # Admin cookies are not sufficient: when admin auth is disabled the
    # application's legacy middleware intentionally allows /api/v1 requests.
    # This standalone secret must always be present; never log its value.
    expected_token = os.environ.get("STOCK_RAZOR_SNAPSHOT_READ_TOKEN", "")
    provided_token = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
    if not expected_token or not provided_token or not hmac.compare_digest(provided_token, expected_token):
        raise HTTPException(status_code=401, detail="snapshot read authorization required")
    if not _SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=400, detail="invalid market symbol")
    service = getattr(request.app.state, "market_snapshot_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="AI Monitor market snapshot runtime unavailable")
    # Only an existing app-lifecycle AI Monitor owner can provide this method;
    # there is no provider fallback, side-effectful bootstrap, or new worker.
    read_snapshot = getattr(service, "get_snapshot", None)
    if not callable(read_snapshot):
        raise HTTPException(status_code=503, detail="AI Monitor market snapshot runtime unavailable")
    result = read_snapshot(symbol.upper())
    if result is None:
        raise HTTPException(status_code=503, detail="market snapshot unavailable")
    return MarketSnapshotResponse.model_validate(result)


@router.get(
    "/vti/bars/{symbol}",
    responses={
        200: {"description": "Read-only VTI bars"},
        400: {"description": "Invalid request"},
        401: {"description": "Valid admin session required"},
        503: {"description": "VTI auth disabled or runtime unavailable"},
    },
    summary="Read secure VTI bars",
    description=(
        "Browser-facing read-only bridge for canonical US bars and the settled-bar cache. "
        "Requires admin auth even when the rest of the legacy API is configured unauthenticated."
    ),
)
def get_vti_bars(
    symbol: str,
    request: Request,
    timeframe: str = Query(default="15m"),
    limit: int = Query(default=240, ge=1, le=480),
    before: str | None = Query(default=None),
):
    _require_vti_session(request)
    if not re.fullmatch(r"(?:US\.)?[A-Z]{1,8}", symbol.strip().upper()):
        raise HTTPException(status_code=400, detail="invalid US market symbol")

    service = getattr(request.app.state, "vti_market_data_service", None)
    if service is None:
        service = VtiMarketDataService()

    try:
        return service.read_us_bars(
            symbol,
            timeframe=timeframe,
            limit=limit,
            before=before,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

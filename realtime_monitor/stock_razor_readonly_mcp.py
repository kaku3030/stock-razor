"""Minimal read-only MCP facade for the existing Stock Razor snapshot API.

This module deliberately does not import the legacy realtime-monitor server,
construct a provider, subscribe, seed history, access OpenD, or expose trading
operations.  The API URL and bearer token are injected through the environment
and the token is sent only as an HTTP header.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from mcp.server.fastmcp import FastMCP
except ModuleNotFoundError:  # pragma: no cover - exercised only without the optional MCP runtime
    FastMCP = None  # type: ignore[assignment,misc]


API_BASE_ENV = "STOCK_RAZOR_READONLY_API_BASE_URL"
TOKEN_ENV = "STOCK_RAZOR_SNAPSHOT_READ_TOKEN"
DEFAULT_TIMEOUT_SECONDS = 10


def _base_url() -> str:
    value = os.environ.get(API_BASE_ENV, "").strip().rstrip("/")
    if not value:
        raise RuntimeError(f"{API_BASE_ENV} is required")
    if not value.startswith("https://"):
        raise RuntimeError(f"{API_BASE_ENV} must use HTTPS")
    return value


def _read_token() -> str:
    value = os.environ.get(TOKEN_ENV, "").strip()
    if not value:
        raise RuntimeError(f"{TOKEN_ENV} is required")
    return value


def _get(path: str) -> dict:
    request = Request(
        f"{_base_url()}{path}",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {_read_token()}",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"snapshot API returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError("snapshot API read failed") from exc


def _symbols(value: Iterable[str]) -> list[str]:
    result = list(dict.fromkeys(str(item).strip().upper() for item in value if str(item).strip()))
    if not result:
        raise ValueError("symbols must contain at least one symbol")
    if len(result) > 20:
        raise ValueError("symbols must contain at most 20 symbols")
    return result


def _snapshot_payload(snapshot: dict, *, timeframe: str | None = None) -> dict:
    bars = list(snapshot.get("bars") or ())
    if timeframe:
        bars = [bar for bar in bars if bar.get("timeframe") == timeframe]
    quote = snapshot.get("quote") or {}
    latest = bars[-1] if bars else quote
    flags = list(dict.fromkeys([
        *(snapshot.get("quality_flags") or ()),
        *(quote.get("quality_flags") or ()),
        *(latest.get("quality_flags") or ()),
    ]))
    evidence = snapshot.get("evidence") or {}
    return {
        "symbol": snapshot.get("symbol"),
        "provider": snapshot.get("provider"),
        "feed": snapshot.get("feed"),
        "source_timestamp": latest.get("source_timestamp"),
        "received_at": latest.get("received_at"),
        "freshness_ms": latest.get("freshness_ms", latest.get("observed_latency_ms")),
        "currentness": snapshot.get("currentness", "UNKNOWN"),
        "session": latest.get("session", "UNKNOWN"),
        "quality_flags": flags,
        "signal_permission": snapshot.get("signal_permission", "UNKNOWN"),
        "runtime_generation": snapshot.get("runtime_generation", evidence.get("runtime_generation")),
        "controller_generation": snapshot.get("controller_generation", "UNKNOWN"),
        "entitlement": snapshot.get("entitlement", "UNKNOWN"),
        "provider_finality": snapshot.get("provider_finality", "UNKNOWN"),
        "delivery_mode": snapshot.get("delivery_mode", "UNKNOWN"),
        "quote": quote,
        "bars": bars,
    }


if FastMCP is None:
    class _UnavailableMCP:
        def tool(self):
            return lambda function: function

        def run(self, transport: str) -> None:
            raise RuntimeError("MCP runtime is unavailable; install realtime_monitor/requirements.txt")

    mcp = _UnavailableMCP()
else:
    mcp = FastMCP(
        "stock-razor-readonly",
        instructions=(
            "Read-only Stock Razor market data. Never place orders, access accounts, "
            "start providers, or treat UNKNOWN entitlement/finality/currentness as PASS."
        ),
    )


@mcp.tool()
def get_market_snapshots(symbols: list[str], timeframe: str = "1m") -> dict:
    """Read current normalized snapshots for symbols from the existing API owner."""
    if timeframe not in {"1m", "15m", "60m", "1h"}:
        raise ValueError("timeframe must be one of: 1m, 15m, 60m, 1h")
    snapshots = []
    for symbol in _symbols(symbols):
        payload = _get(f"/api/v1/data/market-snapshot/{quote(symbol, safe='')}")
        snapshots.append(_snapshot_payload(payload, timeframe=timeframe))
    return {"read_only": True, "timeframe": timeframe, "snapshots": snapshots}


@mcp.tool()
def get_market_bars(symbol: str, timeframe: str = "1m", limit: int = 1) -> dict:
    """Read bars already exposed by the existing normalized snapshot view."""
    if timeframe not in {"1m", "15m", "60m", "1h"}:
        raise ValueError("timeframe must be one of: 1m, 15m, 60m, 1h")
    if not isinstance(limit, int) or not 1 <= limit <= 480:
        raise ValueError("limit must be between 1 and 480")
    payload = _get(f"/api/v1/data/market-snapshot/{quote(symbol.strip().upper(), safe='')}")
    result = _snapshot_payload(payload, timeframe=timeframe)
    result["bars"] = result["bars"][-limit:]
    result["availability_note"] = (
        "The current API view exposes the latest bar per available timeframe; "
        "history requires a separately authorized historical-data surface."
    )
    return {"read_only": True, **result}


@mcp.tool()
def get_livefeed_health() -> dict:
    """Return read-only provider/runtime health from the existing API surface."""
    return {
        "read_only": True,
        "status": "UNKNOWN",
        "reason": "The current API exposes per-snapshot health only; no provider or controller health endpoint is wired.",
        "entitlement": "UNKNOWN",
        "provider_finality": "UNKNOWN",
    }


def main() -> None:
    mcp.run(transport=os.environ.get("STOCK_RAZOR_MCP_TRANSPORT", "streamable-http"))


if __name__ == "__main__":
    main()

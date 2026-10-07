"""Canonical minimal read-only MCP surface for cloud runtime health."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from data_provider.cn_cloud_runtime_reader import read_cn_market_data
from data_provider.cn_radar_runtime_reader import read_cn_radar_analysis
from data_provider.futures_runtime_health import read_futures_runtime_health
from data_provider.us_canonical_runtime_reader import (
    read_us_livefeed_health,
    read_us_market_bars,
    read_us_market_snapshots,
)
from data_provider.us_radar_runtime_reader import read_us_radar_analysis

mcp = FastMCP("stock-razor-readonly")


@mcp.tool()
def get_futures_runtime_health() -> dict:
    """Return fail-closed Futures runtime heartbeat health evidence."""
    return read_futures_runtime_health()


@mcp.tool()
def get_cn_market_analysis(symbols: list[str] | None = None) -> dict:
    """Return precomputed A-share cloud Radar research state without recomputation."""
    return read_cn_radar_analysis(symbols)


@mcp.tool()
def get_cn_market_data(
    symbol: str,
    timeframe: str = "1d",
    limit: int = 120,
) -> dict:
    """Return bounded A-share cloud observation rows without provider I/O."""
    return read_cn_market_data(symbol, timeframe=timeframe, limit=limit)


@mcp.tool()
def get_livefeed_health() -> dict:
    """Return compact fail-closed US livefeed and canonical-cache health."""
    return read_us_livefeed_health()


@mcp.tool()
def get_market_snapshots(symbols: list[str] | None = None) -> dict:
    """Return latest canonical 1m/5m/15m/1h facts without provider I/O."""
    return read_us_market_snapshots(symbols)


@mcp.tool()
def get_market_analysis(symbols: list[str] | None = None) -> dict:
    """Return the latest precomputed US Radar research state without recomputation."""
    return read_us_radar_analysis(symbols)


@mcp.tool()
def get_market_bars(
    symbol: str,
    timeframe: str = "15m",
    limit: int = 100,
) -> dict:
    """Return bounded canonical US bars from the cloud-local snapshot."""
    return read_us_market_bars(symbol, timeframe=timeframe, limit=limit)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

"""Canonical minimal read-only MCP surface for cloud runtime health."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from data_provider.futures_runtime_health import read_futures_runtime_health

mcp = FastMCP("stock-razor-readonly")


@mcp.tool()
def get_futures_runtime_health() -> dict:
    """Return fail-closed Futures runtime heartbeat health evidence."""
    return read_futures_runtime_health()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

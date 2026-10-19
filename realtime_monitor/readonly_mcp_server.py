"""Canonical minimal read-only MCP surface for cloud runtime health."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from data_provider.cloud_ops_readonly_status import read_cloud_ops_status
from data_provider.cn_cloud_runtime_reader import read_cn_market_data
from data_provider.cn_radar_runtime_reader import read_cn_radar_analysis
from data_provider.cn_fast_research_brief import read_cn_quick_scan
from data_provider.futures_runtime_health import read_futures_runtime_health
from data_provider.tickflow_cloud_probe_reader import read_tickflow_probe_health
from data_provider.cn_tickflow_research_cache import read_cn_tickflow_research_data
from data_provider.market_source_status import read_market_source_status
from data_provider.us_canonical_runtime_reader import (
    read_us_livefeed_health,
    read_us_market_bars,
    read_us_market_snapshots,
)
from data_provider.us_historical_cache_reader import read_us_historical_bars
from data_provider.us_radar_runtime_reader import read_us_radar_analysis
from data_provider.us_fast_research_brief import read_us_fast_research_brief, read_us_quick_scan
from src.services.context_manager import default_store

mcp = FastMCP("stock-razor-readonly")


@mcp.tool()
def get_context_manager_state() -> dict:
    """Restore the compact engineering context; expired or invalid state stays blocked."""
    return default_store().read()


@mcp.tool()
def get_cloud_ops_status() -> dict:
    """EC2-local services and heartbeats only: no AWS APIs or mutations."""
    return read_cloud_ops_status()


@mcp.tool()
def get_futures_runtime_health() -> dict:
    """Return fail-closed Futures runtime heartbeat health evidence."""
    return read_futures_runtime_health()


@mcp.tool()
def get_market_source_status(cn_symbol: str = "159611.SZ") -> dict:
    """Single cached status for US OpenD, CN Eastmoney/Tencent and TickFlow probe."""
    return read_market_source_status(cn_symbol)


@mcp.tool()
def get_tickflow_probe_health() -> dict:
    """Read sanitized AWS TickFlow probe evidence, never live TickFlow market data."""
    return read_tickflow_probe_health()


@mcp.tool()
def get_cn_tickflow_research_data(
    symbol: str = "159611.SZ",
    timeframe: str = "15m",
    limit: int = 30,
    research_mode: str = "session_progress",
) -> dict:
    """Read direct AWS Premium TickFlow 1m/5m/15m/60m/1d cache, strictly research-only.

    Uses no provider network requests, never marks current candle finalized,
    never asserts Radar/Source Arbiter admission or trading permission.
    """
    return read_cn_tickflow_research_data(
        symbol, timeframe=timeframe, limit=limit, research_mode=research_mode,
    )


# Backward-compatible compact path for ChatGPT's existing frozen tool snapshot.
# Exact sentinel only; every ordinary symbol request keeps its original result.
_CN_QUICK_SCAN_COMPAT_REQUEST = ["__QUICK_SCAN__"]


@mcp.tool()
def get_cn_market_analysis(symbols: list[str] | None = None) -> dict:
    """Return precomputed A-share Radar research.

    Use symbols=["__QUICK_SCAN__"] for the bounded read-only quick scan
    while an existing ChatGPT app action snapshot lacks get_cn_quick_scan.
    The exact __CONTEXT_MANAGER_STATE__ singleton restores read-only context.
    All other requests keep the original response and safety contract.
    """
    if symbols == _CN_QUICK_SCAN_COMPAT_REQUEST:
        return read_cn_quick_scan()
    if symbols == ["__CONTEXT_MANAGER_STATE__"]:
        return get_context_manager_state()
    return read_cn_radar_analysis(symbols)


@mcp.tool()
def get_cn_quick_scan(symbols: list[str] | None = None) -> dict:
    """Small, one-call precomputed CN research preview; always ENTRY_BLOCKED."""
    return read_cn_quick_scan(symbols)


def _read_tickflow_historical_batch(limit: int, *, full: bool=False) -> dict:
    """One remote MCP round trip for the bounded TickFlow research set; no provider IO.

    Five or twenty independent cache reads must share a source SHA and sequence.
    Never promote an incomplete or misaligned set to a usable batch.
    """
    base = {
        "ok": False, "status": "INVALID_REQUEST",
        "provider": "TICKFLOW_PREMIUM", "research_only": True,
        "bar_finality": "NOT_VERIFIED", "currentness": "UNPROVEN",
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED", "can_confirm_signal": False,
        "live_trade": False, "provider_requests": 0,
        "canonical_write_authorized": False,
        "research_mode": "historical_only",
    }
    if type(full) is not bool:
        return base
    periods=(("1m","5m","15m","60m","1d") if full else ("15m","60m"))
    if type(limit) is not int or not 1 <= limit <= (240 if full else 24):
        return base
    raw = {}
    states = {}
    source_versions = set()
    symbols = ("159611.SZ", "159209.SZ", "518880.SH", "512730.SH", "159363.SZ")
    for symbol in symbols:
        frames = {}
        for period in periods:
            result = read_cn_tickflow_research_data(
                symbol, timeframe=period, limit=limit,
                research_mode="historical_only",
            )
            states[f"{symbol}:{period}"] = result.get("status", "INVALID_CACHE")
            if not (
                result.get("ok") is True
                and result.get("status") == "PASS_HISTORICAL_ONLY"
                and result.get("research_only") is True
                and result.get("radar_admission") == "BLOCKED"
                and result.get("source_arbiter_admission") == "BLOCKED"
                and result.get("live_trade") is False
                and result.get("bar_finality") == "NOT_VERIFIED"
                and result.get("provider_requests") == 0
                and isinstance(result.get("rows"), list)
                and len(result["rows"]) > 0
            ):
                return {**base, "status": "PARTIAL_OR_STALE",
                        "frame_status": states}
            version = (result.get("repo_sha"), result.get("sequence"))
            if not isinstance(version[0], str) or len(version[0]) != 40 or type(version[1]) is not int:
                return {**base, "status": "INVALID_SOURCE_ALIGNMENT",
                        "frame_status": states}
            source_versions.add(version)
            frames[period] = {
                "rows": result["rows"],
                "expected_grid_progress": result.get("expected_grid_progress"),
                "latest_bar_age_seconds": result.get("last_bar_end_label_age_seconds"),
                "source_age_seconds": result.get("source_age_seconds"),
            }
        raw[symbol] = frames
    if len(source_versions) != 1:
        return {**base, "status": "INVALID_SOURCE_ALIGNMENT",
                "frame_status": states}
    sha, sequence = next(iter(source_versions))
    return {
        **base, "ok": True, "status": "PASS_HISTORICAL_ONLY",
        "repo_sha": sha, "sequence": sequence,
        "symbols": raw, "frame_status": states,
        "frame_count": len(symbols)*len(periods),
        "source_age_seconds": max(
            frame["source_age_seconds"]
            for frames in raw.values() for frame in frames.values()
        ),
    }


def _read_tickflow_fast_snapshot() -> dict:
    """Compact TickFlow-symbol/2-timeframe historical watchlist, never live advice.

    Calls the same four-source-aligned, fail-closed research reader as BATCH.
    No TickFlow provider network I/O and no cached state held in the MCP.
    """
    from time import perf_counter

    start = perf_counter()
    full = _read_tickflow_historical_batch(1)
    common = {
        "ok": False,
        "status": full.get("status", "INVALID_CACHE"),
        "provider": "TICKFLOW_PREMIUM",
        "research_only": True,
        "bar_finality": "NOT_VERIFIED",
        "currentness": "UNPROVEN",
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "can_confirm_signal": False,
        "canonical_write_authorized": False,
        "provider_requests": 0,
        "research_mode": "historical_only",
        "frame_count": 10,
        "read_scope": "CLOUD_MCP_LOCAL_CACHE_NOT_CHATGPT_RTT",
    }
    if not full.get("ok") or full.get("status") != "PASS_HISTORICAL_ONLY":
        return {**common, "frame_status": full.get("frame_status", {}),
                "read_ms": round((perf_counter() - start) * 1000, 2)}
    latest = {}
    for symbol in ("159611.SZ", "159209.SZ", "518880.SH", "512730.SH", "159363.SZ"):
        frames = {}
        for tf in ("15m", "60m"):
            detail = full["symbols"][symbol][tf]
            rows = detail["rows"]
            if len(rows) != 1:
                return {**common, "status": "INVALID_BATCH_FRAME"}
            row = rows[0]
            # Preserve native float precision and explicit unknown finality.
            frames[tf] = {
                "t": row["label"],
                "o": row["open"], "h": row["high"],
                "l": row["low"], "c": row["close"],
                "v": row["volume"], "a": row["amount"],
                "amount_availability": row["amount_availability"],
                "ohlc_validation": row["ohlc_validation"],
                "expected_grid_progress": detail["expected_grid_progress"],
                "is_partial_bar": True,
                "bar_finality": "NOT_VERIFIED",
            }
        latest[symbol] = frames
    return {
        **common, "ok": True, "status": "PASS_HISTORICAL_ONLY",
        "repo_sha": full["repo_sha"], "sequence": full["sequence"],
        "source_age_seconds": full["source_age_seconds"],
        "symbols": latest,
        "read_ms": round((perf_counter() - start) * 1000, 2),
    }


@mcp.tool()
def get_cn_market_data(
    symbol: str,
    timeframe: str = "1d",
    limit: int = 120,
) -> dict:
    """Read cached CN data; TICKFLOW: selects native historical research only.

    The exact opt-in prefix preserves the old ChatGPT MCP tool schema.
    Other symbols retain the existing Eastmoney/Tencent observation path.
    """
    if symbol == "TICKFLOW:FAST":
        return _read_tickflow_fast_snapshot()
    if symbol == "TICKFLOW:BATCH":
        return _read_tickflow_historical_batch(limit)
    if symbol == "TICKFLOW:FULL":
        return _read_tickflow_historical_batch(limit, full=True)
    # Opt in to due-grid progress, not exchange finality or source admission.
    # Keep historical-only and normal Eastmoney/Tencent routes unchanged.
    if isinstance(symbol, str) and symbol.startswith("TICKFLOW:PROGRESS:"):
        return read_cn_tickflow_research_data(
            symbol[len("TICKFLOW:PROGRESS:"):],
            timeframe=timeframe, limit=limit, research_mode="session_progress",
        )
    if isinstance(symbol, str) and symbol.startswith("TICKFLOW:"):
        return read_cn_tickflow_research_data(
            symbol[len("TICKFLOW:"):], timeframe=timeframe, limit=limit,
            research_mode="historical_only",
        )
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
    """US Radar research, or exact compatibility alias for Cloud Ops read-only health.

    Existing ChatGPT connector action catalogs may lag the deployed MCP tools.
    Only the full literal singleton sentinel redirects to the already reviewed
    local-only Cloud Ops reader. The exact __CONTEXT_MANAGER_STATE__
    singleton routes to the fail-closed read-only Context Manager state.
    Every ordinary Radar request is unchanged.
    """
    if symbols == ["__CLOUD_OPS_STATUS__"]:
        return read_cloud_ops_status()
    if symbols == ["__CONTEXT_MANAGER_STATE__"]:
        return get_context_manager_state()
    return read_us_radar_analysis(symbols)


@mcp.tool()
def get_us_research_brief(symbols: list[str] | None = None) -> dict:
    """Get compact US 1m/5m/15m/1h plus precomputed Radar evidence in one call.

    SOURCE_SHA, runtime, sequence and freshness must align. No provider I/O
    or LLM reasoning runs here; trading and signal gates stay closed.
    """
    return read_us_fast_research_brief(symbols)


@mcp.tool()
def get_us_quick_scan(symbols: list[str] | None = None) -> dict:
    """Fast compact US watchlist: prices, 1m/5m/15m/1h bar finality, Radar trends.

    One aligned cloud-cache read, no provider or LLM calls. All trading gates
    remain blocked; partial bars and stale data never qualify as signals.
    """
    return read_us_quick_scan(symbols)


@mcp.tool()
def get_market_bars(
    symbol: str,
    timeframe: str = "15m",
    limit: int = 100,
) -> dict:
    """Return bounded canonical US bars from the cloud-local snapshot."""
    return read_us_market_bars(symbol, timeframe=timeframe, limit=limit)


@mcp.tool()
def get_historical_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    timeframe: str = "1h",
    adjustment: str = "qfq",
    session: str = "RTH",
    limit: int = 100,
    cursor: str | None = None,
) -> dict:
    """Read bounded historical bars from the persisted cache only."""
    return read_us_historical_bars(
        symbol,
        start_date=start_date,
        end_date=end_date,
        timeframe=timeframe,
        adjustment=adjustment,
        session=session,
        limit=limit,
        cursor=cursor,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

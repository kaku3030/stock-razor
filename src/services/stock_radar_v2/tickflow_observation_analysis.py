"""Adapt one private TickFlow cache to the existing non-actionable CN Radar."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from data_provider.cn_tickflow_research_cache import SYMBOLS, read_cn_tickflow_research_data
from src.services.stock_radar_v2.cn_observation_analysis import (
    TICKFLOW_RADAR_INPUT_SCHEMA, evaluate_cn_observation_payload,
)


def validate_tickflow_source_clock(source: dict, now: datetime) -> datetime:
    """Recheck age even when a worker reuses an unchanged evaluation."""
    observed = datetime.fromisoformat(source["observed_at_utc"])
    if now.tzinfo is None or observed.tzinfo is None:
        raise ValueError("TICKFLOW_CLOCK_INVALID")
    max_age = 1080 if now.astimezone(ZoneInfo("Asia/Shanghai")).weekday() >= 5 else 360
    if not 0 <= (now - observed).total_seconds() <= max_age:
        raise ValueError("TICKFLOW_CACHE_STALE_OR_FUTURE")
    return observed


def evaluate_tickflow_observation_payload(source: dict, *, now_utc: datetime) -> dict:
    """Four existing baseline symbols, cached D1/60m/15m, no provider I/O.

    Historical research only: no source entitlement, closed-bar, volume-unit
    or adjustment promotion. The cache has no runtime UUID; report UNKNOWN.
    """
    observed = validate_tickflow_source_clock(source, now_utc)
    if type(source.get("sequence")) is not int or source["sequence"] < 1:
        raise ValueError("TICKFLOW_SEQUENCE_INVALID")
    symbols = {}
    for symbol in SYMBOLS:
        frames = {}
        for period in ("1d", "60m", "15m"):
            frame = read_cn_tickflow_research_data(
                symbol, period, 240, now_utc=now_utc,
                research_mode="historical_only", observation=source,
            )
            if frame.get("ok") is not True:
                raise ValueError("TICKFLOW_FRAME_NOT_VALIDATED")
            frames[period] = {
                "status": "PASS", "provider_used": "TICKFLOW_PREMIUM",
                "provider_lineage": "tickflow", "source_symbol": symbol,
                "timestamp_semantic": ("DAILY_DATE" if period == "1d"
                                       else "BAR_END_GRID_MATCH_HISTORICAL_ONLY"),
                "currentness": "UNPROVEN",
                "rows": [{**row, "volume_raw": row["volume"],
                          "volume_unit": "NOT_VERIFIED"} for row in frame["rows"]],
            }
        symbols[symbol.split(".")[0]] = {
            "status": "PASS", "timeframes": frames,
            "providers_used": ["TICKFLOW_PREMIUM"],
            "provider_policy": "TICKFLOW_CACHE_HISTORICAL_RESEARCH_ONLY",
            "intraday_timestamp_semantics_proven": False,
            "intraday_currentness_proven": False,
            "radar_admission": "BLOCKED", "live_trade": False,
        }
    normalized = {
        "schema": TICKFLOW_RADAR_INPUT_SCHEMA, "repo_sha": source["repo_sha"],
        "runtime_instance_id": "NOT_VERIFIED", "sequence": source["sequence"],
        "emitted_at_utc": observed.astimezone(timezone.utc).isoformat(),
        "symbols": symbols, "provider_lineages": ["tickflow"],
        "provider_policy": "TICKFLOW_CACHE_HISTORICAL_RESEARCH_ONLY",
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True, "can_confirm_signal": False,
        "radar_admission": "BLOCKED", "live_trade": False,
    }
    result = evaluate_cn_observation_payload(normalized)
    result.update(provider_requests=0, bar_finality="NOT_VERIFIED",
                  source_arbiter_admission="BLOCKED")
    for item in result["symbols"].values():
        if item.get("status") == "RESEARCH_STATE":
            if any(warning.endswith("_insufficient_bars")
                   for period in ("hourly", "intraday")
                   for warning in item["technical"][period]["quality"]["warnings"]):
                item["technical"]["risk_flags"].append("tickflow_indicator_history_insufficient")
            item["technical"]["risk_flags"].extend([
                "tickflow_bar_finality_not_verified", "tickflow_volume_units_not_verified",
                "tickflow_adjustment_not_verified",
            ])
    return result

"""Bounded single-call read-only US market/Radar brief for Main Control.

No live providers, no LLM calls, no recomputation, no financial orders. Both
snapshots must have matching SHA + producer runtime identity + sequence before
technical research is paired with prices. Everything remains research-only.
"""
from __future__ import annotations

from time import perf_counter
from typing import Iterable

from data_provider.us_canonical_runtime_reader import read_us_market_snapshots
from data_provider.us_radar_runtime_reader import read_us_radar_analysis

MAX_BRIEF_SYMBOLS = 12


def _frame_summary(value: object) -> dict:
    if not isinstance(value, dict):
        return {"trend": "unknown", "quality": {"status": "missing"}}
    q = value.get("quality")
    q = q if isinstance(q, dict) else {}
    return {
        "trend": value.get("trend", "unknown"),
        "momentum": value.get("momentum", "unknown"),
        "volume_state": value.get("volume_state", "unknown"),
        "structure_score": value.get("structure_score"),
        "confidence": value.get("confidence"),
        "indicators": value.get("indicators") if isinstance(value.get("indicators"), dict) else {},
        "quality": {
            "status": q.get("status", "unknown"),
            "bars": q.get("bars"),
            "as_of": q.get("as_of"),
            "is_partial_bar": q.get("is_partial_bar"),
            "warnings": list(q.get("warnings") or ()),
        },
    }


def _brief_symbol(market: dict, radar: dict) -> dict:
    state = radar.get("technical_state")
    state = state if isinstance(state, dict) else {}
    technical = state.get("technical")
    technical = technical if isinstance(technical, dict) else {}
    structure = technical.get("structure")
    structure = structure if isinstance(structure, dict) else {}
    latest = market.get("latest")
    latest = latest if isinstance(latest, dict) else {}
    return {
        "provider": market.get("provider"),
        "feed": market.get("feed"),
        "data_health": market.get("health"),
        "bar_counts": market.get("counts"),
        "latest_bars": {period: latest.get(period) for period in ("1m", "5m", "15m", "1h")},
        "daily": _frame_summary(technical.get("daily")),
        "hourly": _frame_summary(technical.get("hourly")),
        "intraday_15m": _frame_summary(technical.get("intraday")),
        "timeframe_alignment": technical.get("alignment", "unknown"),
        "structure": {
            "trend_sequence": structure.get("trend_sequence", "unknown"),
            "structure_state": structure.get("structure_state", "unknown"),
            "support_levels": list(structure.get("support_levels") or ()),
            "resistance_levels": list(structure.get("resistance_levels") or ()),
            "volume_confirmation": structure.get("volume_confirmation", "unknown"),
            "atr_risk_percent": structure.get("atr_risk_percent"),
            "confidence": structure.get("confidence"),
        },
        "research_score": technical.get("research_score"),
        "risk_flags": list(technical.get("risk_flags") or ()),
        "watch_conditions": list(technical.get("watch_conditions") or ()),
        "radar_symbol_status": radar.get("status"),
        "radar_reasons": list(radar.get("reasons") or ()),
        "signal_permission": "BLOCKED",
    }


def read_us_market_brief(
    symbols: Iterable[str] | None = None,
    *,
    radar_path: str | None = None,
    snapshot_path: str | None = None,
    now_utc=None,
) -> dict:
    """One local MCP call for existing read-only research and latest price facts.

    The reader does not make entry/exit recommendations. Read latency measures
    only local file snapshots and assembly, not MCP/LLM or market-event E2E.
    """
    started = perf_counter()
    selected = None if symbols is None else list(symbols)
    safe = {
        "research_only": True,
        "can_confirm_signal": False,
        "signal_permission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False,
        "order_execution": False,
        "end_to_end_latency_qualified": False,
    }

    def finish(status: str, *, reasons: list[str], **extra) -> dict:
        return {
            **safe,
            **extra,
            "status": status,
            "reasons": reasons,
            "read_latency_ms": round((perf_counter() - started) * 1000, 3),
        }

    if selected is not None and (not 1 <= len(selected) <= MAX_BRIEF_SYMBOLS or
                                  any(not isinstance(value, str) or not value.strip() for value in selected)):
        return finish("INVALID_ARGUMENT", reasons=["INVALID_SYMBOL_REQUEST"],
                      symbols={}, missing_symbols=[])

    radar = read_us_radar_analysis(selected, path=radar_path, now_utc=now_utc)
    market = read_us_market_snapshots(selected, path=snapshot_path, now_utc=now_utc)
    sources = {
        "radar": {
            "status": radar.get("status"),
            "poll_status": radar.get("poll_status"),
            "worker_repo_sha": radar.get("worker_repo_sha"),
            "expected_source_repo_sha": radar.get("expected_source_repo_sha"),
            "source_runtime_instance_id": radar.get("source_runtime_instance_id"),
            "source_sequence": radar.get("source_sequence"),
            "emitted_at_utc": radar.get("emitted_at_utc"),
            "source_age_seconds": radar.get("source_age_seconds"),
            "analysis_ms": radar.get("radar_analysis_latency_ms"),
            "canonical_export_to_radar_ms": radar.get("data_to_radar_latency_ms"),
        },
        "canonical": {
            "status": market.get("status"),
            "repo_sha": market.get("repo_sha"),
            "runtime_instance_id": market.get("runtime_instance_id"),
            "sequence": market.get("sequence"),
            "emitted_at_utc": market.get("emitted_at_utc"),
            "source_age_seconds": market.get("source_age_seconds"),
            "delivery_mode": market.get("delivery_mode"),
            "bar_closure": market.get("bar_closure"),
        },
    }
    if radar.get("ok") is not True or market.get("ok") is not True:
        return finish("UNAVAILABLE", reasons=["READER_UNAVAILABLE_OR_INVALID"],
                      sources=sources, symbols={}, missing_symbols=[])

    if (
        not isinstance(market.get("sequence"), int)
        or isinstance(market.get("sequence"), bool)
        or market.get("sequence") <= 0
        or radar.get("source_sequence") != market.get("sequence")
        or radar.get("expected_source_repo_sha") != market.get("repo_sha")
        or not radar.get("source_runtime_instance_id")
        or radar.get("source_runtime_instance_id") != market.get("runtime_instance_id")
    ):
        # No misleading composite when one worker is behind the other.
        return finish("MISALIGNED", reasons=["SOURCE_PROVENANCE_OR_SEQUENCE_MISMATCH"],
                      sources=sources, symbols={}, missing_symbols=[])

    if radar.get("poll_status") not in ("PASS", "UNCHANGED"):
        return finish("BLOCKED", reasons=["RADAR_EVALUATION_NOT_PASS"],
                      sources=sources, symbols={}, missing_symbols=[])

    market_symbols = market.get("symbols") or {}
    radar_symbols = radar.get("symbols") or {}
    if not isinstance(market_symbols, dict) or not isinstance(radar_symbols, dict):
        return finish("INVALID", reasons=["INVALID_SYMBOL_MAP"],
                      sources=sources, symbols={}, missing_symbols=[])

    names = (
        [str(value).strip().upper() if "." in str(value) else "US." + str(value).strip().upper() for value in selected]
        if selected is not None
        else sorted(set(market_symbols) & set(radar_symbols))[:MAX_BRIEF_SYMBOLS]
    )
    names = list(dict.fromkeys(names))
    present = {
        name: _brief_symbol(market_symbols[name], radar_symbols[name])
        for name in names
        if isinstance(market_symbols.get(name), dict)
        and isinstance(radar_symbols.get(name), dict)
    }
    missing = [name for name in names if name not in present]
    stale = radar.get("status") != "PASS" or market.get("status") != "PASS"
    reasons = (["SOURCE_NOT_FRESH"] if stale else []) + (["SYMBOLS_MISSING"] if missing else [])
    return finish(
        "DEGRADED" if reasons else "ALIGNED_RESEARCH",
        reasons=reasons,
        sources=sources,
        symbols=present,
        missing_symbols=missing,
        price_and_radar_sequence_aligned=True,
        read_scope="LOCAL_CANONICAL_AND_PRECOMPUTED_RADAR_ONLY",
    )

"""One-read-only-MCP-call, fail-closed US research brief for Main Control.

Provides precomputed market facts plus Radar study state. It NEVER recalculates
indicators, queries a provider, decides a trade, or silently accepts a mismatch
between producer and Radar provenance. A PASS-like result means *source aligned*
research only; all trading and signal authority remains BLOCKED.
"""
from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Iterable

from data_provider.us_canonical_runtime_reader import read_us_market_snapshots
from data_provider.us_radar_runtime_reader import read_us_radar_analysis

_MAX_SYMBOLS = 8
_TIMEFRAMES = ("1m", "5m", "15m", "1h")
_BAR_FIELDS = (
    "bar_end_utc", "close", "volume", "is_closed", "is_complete",
    "quality_flags", "session", "freshness_ms",
)
_FRAME_FIELDS = (
    "timeframe", "trend", "momentum", "volume_state",
    "confidence", "summary",
)


def _symbol(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    symbol = value.strip().upper()
    if not symbol:
        return None
    if "." not in symbol:
        symbol = "US." + symbol
    if not symbol.startswith("US."):
        return None
    ticker = symbol[3:]
    if not ticker or len(ticker) > 16 or any(ch not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in ticker):
        return None
    return symbol


def _frame(raw: object) -> dict:
    item = raw if isinstance(raw, dict) else {}
    quality = item.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    indicators = item.get("indicators")
    indicators = indicators if isinstance(indicators, dict) else {}
    return {
        **{key: item.get(key) for key in _FRAME_FIELDS},
        "indicators": indicators,
        "quality": {
            "status": quality.get("status", "UNKNOWN"),
            "bars": quality.get("bars"),
            "as_of": quality.get("as_of"),
            "is_partial_bar": quality.get("is_partial_bar"),
            "warnings": quality.get("warnings") or [],
        },
    }


def _symbol_research(price: dict, studied: dict) -> dict:
    latest = price.get("latest")
    latest = latest if isinstance(latest, dict) else {}
    technical_state = studied.get("technical_state")
    technical_state = technical_state if isinstance(technical_state, dict) else {}
    technical = technical_state.get("technical")
    technical = technical if isinstance(technical, dict) else {}
    structure = technical.get("structure")
    structure = structure if isinstance(structure, dict) else {}
    technical_quality = technical_state.get("quality_flags") or []
    bars = {}
    for timeframe in _TIMEFRAMES:
        observed = latest.get(timeframe)
        bars[timeframe] = (
            {key: observed.get(key) for key in _BAR_FIELDS}
            if isinstance(observed, dict)
            else None
        )
    return {
        "latest_bars": bars,
        "bar_counts": price.get("counts") or {},
        "health": price.get("health"),
        "provider": price.get("provider"),
        "feed": price.get("feed"),
        "multitimeframe": {
            "daily": _frame(technical.get("daily")),
            "hourly": _frame(technical.get("hourly")),
            "intraday_15m": _frame(technical.get("intraday")),
            "alignment": technical.get("alignment", "UNKNOWN"),
            "state_summary": technical.get("state_summary"),
            "research_score": technical.get("research_score"),
            "risk_flags": technical.get("risk_flags") or [],
            "watch_conditions": technical.get("watch_conditions") or [],
            "structure": {
                key: structure.get(key) for key in (
                    "trend_sequence", "structure_state", "support_levels",
                    "resistance_levels", "vwap_position", "volume_confirmation",
                    "atr_risk_percent", "confidence",
                )
            },
        },
        "technical_as_of": technical_state.get("as_of"),
        "technical_quality_flags": technical_quality,
        "research_evidence_reasons": studied.get("reasons") or [],
        "signal_permission": "BLOCKED",
        "trading_authority": False,
    }


def read_us_fast_research_brief(
    symbols: Iterable[str] | None = None,
    *,
    snapshot_path: str | None = None,
    radar_path: str | None = None,
    now_utc: datetime | None = None,
) -> dict:
    """Read two existing local sources once each; never rely on chat cache.

    The common 'now' is reused for both freshness checks. Source mismatch,
    missing symbols, stale snapshots or malformed arguments BLOCK the entire
    bundle, instead of mixing old technical conclusions with new prices.
    """
    started = perf_counter()
    safety = {
        "schema": "stock_razor_us_fast_research_brief_v0_1",
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False,
        "trading_authority": False,
        "provider_to_radar_e2e": "NOT_VERIFIED",
        "model_inference_performed": False,
        "provider_requests": 0,
    }

    def finish(**fields: object) -> dict:
        return {**safety, **fields, "read_latency_ms": round((perf_counter() - started) * 1000, 3)}

    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        return finish(ok=False, status="BLOCKED", reasons=["INVALID_CLOCK"], symbols={})
    now = now.astimezone(timezone.utc)
    if symbols is not None:
        if isinstance(symbols, (str, bytes)):
            return finish(ok=False, status="INVALID_ARGUMENT", reasons=["INVALID_SYMBOL_LIST"], symbols={})
        values = list(symbols)
        if not 1 <= len(values) <= _MAX_SYMBOLS:
            return finish(ok=False, status="INVALID_ARGUMENT", reasons=["INVALID_SYMBOL_COUNT"], symbols={})
        requested = tuple(dict.fromkeys(_symbol(v) for v in values))
        if None in requested:
            return finish(ok=False, status="INVALID_ARGUMENT", reasons=["INVALID_SYMBOL"], symbols={})
    else:
        requested = ()

    try:
        market = read_us_market_snapshots(
            list(requested) if requested else None,
            path=snapshot_path,
            now_utc=now,
        )
        radar = read_us_radar_analysis(
            list(requested) if requested else None,
            path=radar_path,
            now_utc=now,
        )
    except (OSError, ValueError, TypeError):
        return finish(ok=False, status="BLOCKED", reasons=["SOURCE_READER_ERROR"], symbols={})

    reasons = []
    if market.get("ok") is not True or market.get("status") != "PASS":
        reasons.append("MARKET_SOURCE_NOT_FRESH_AND_VALID")
    if radar.get("ok") is not True or radar.get("status") != "PASS":
        reasons.append("RADAR_SOURCE_NOT_FRESH_AND_VALID")
    # A freshly-written Worker heartbeat is NOT proof it accepted its source.
    # An unchanged-but-qualified sequence remains usable for read-only study;
    # a BLOCKED/UNKNOWN poll must never be laundered into an aligned brief.
    if radar.get("poll_status") not in {"PASS", "UNCHANGED"}:
        reasons.append("RADAR_CURRENT_POLL_NOT_VALID")
    if not market.get("repo_sha") or market.get("repo_sha") != radar.get("expected_source_repo_sha"):
        reasons.append("SOURCE_REPO_SHA_MISMATCH")
    if not market.get("runtime_instance_id") or market.get("runtime_instance_id") != radar.get("source_runtime_instance_id"):
        reasons.append("SOURCE_RUNTIME_ID_MISMATCH")
    if (
        isinstance(market.get("sequence"), bool)
        or not isinstance(market.get("sequence"), int)
        or market.get("sequence") != radar.get("source_sequence")
    ):
        reasons.append("SOURCE_SEQUENCE_NOT_ALIGNED")
    if market.get("delivery_mode") != radar.get("source_delivery_mode"):
        reasons.append("SOURCE_DELIVERY_MODE_NOT_ALIGNED")
    if market.get("bar_closure") != radar.get("source_bar_closure"):
        reasons.append("SOURCE_BAR_CLOSURE_NOT_ALIGNED")

    source_symbols = market.get("symbols")
    research_symbols = radar.get("symbols")
    source_symbols = source_symbols if isinstance(source_symbols, dict) else {}
    research_symbols = research_symbols if isinstance(research_symbols, dict) else {}
    selected = requested or tuple(sorted(set(source_symbols) | set(research_symbols)))
    if len(selected) > _MAX_SYMBOLS:
        reasons.append("TOO_MANY_SYMBOLS")
    missing = tuple(symbol for symbol in selected if symbol not in source_symbols or symbol not in research_symbols)
    if missing:
        reasons.append("SYMBOL_EVIDENCE_INCOMPLETE")

    provenance = {
        "market_repo_sha": market.get("repo_sha"),
        "market_runtime_instance_id": market.get("runtime_instance_id"),
        "market_sequence": market.get("sequence"),
        "market_emitted_at_utc": market.get("emitted_at_utc"),
        "market_age_seconds": market.get("source_age_seconds"),
        "radar_worker_repo_sha": radar.get("worker_repo_sha"),
        "radar_expected_market_repo_sha": radar.get("expected_source_repo_sha"),
        "radar_source_runtime_instance_id": radar.get("source_runtime_instance_id"),
        "radar_source_sequence": radar.get("source_sequence"),
        "radar_emitted_at_utc": radar.get("emitted_at_utc"),
        "radar_age_seconds": radar.get("source_age_seconds"),
        "radar_poll_status": radar.get("poll_status"),
        "source_bar_closure": radar.get("source_bar_closure"),
        "source_delivery_mode": radar.get("source_delivery_mode"),
        "radar_analysis_latency_ms": radar.get("radar_analysis_latency_ms"),
        "canonical_export_to_radar_last_ms": radar.get("data_to_radar_latency_ms"),
    }
    if reasons:
        return finish(
            ok=False, status="BLOCKED", reasons=list(dict.fromkeys(reasons)),
            missing_symbols=list(missing), provenance=provenance, symbols={},
            observed_at_utc=now.isoformat(),
        )

    return finish(
        ok=True, status="ALIGNED_RESEARCH_ONLY",
        reasons=["SIGNAL_AND_TRADING_ADMISSION_NOT_AUTHORIZED"],
        missing_symbols=[], provenance=provenance,
        observed_at_utc=now.isoformat(),
        symbols={
            symbol: _symbol_research(source_symbols[symbol], research_symbols[symbol])
            for symbol in selected
        },
    )



def read_us_quick_scan(
    symbols: Iterable[str] | None = None,
    *,
    snapshot_path: str | None = None,
    radar_path: str | None = None,
    now_utc: datetime | None = None,
) -> dict:
    """Small read-only MCP payload for fast watchlist review.

    Reuses the canonical aligned brief and its fail-closed gates; this is
    projection only, not a new provider call or a trading signal.
    """
    started = perf_counter()
    full = read_us_fast_research_brief(
        symbols, snapshot_path=snapshot_path, radar_path=radar_path,
        now_utc=now_utc,
    )
    common = {
        "schema": "stock_razor_us_quick_scan_v0_1",
        "ok": full.get("ok") is True,
        "status": full.get("status", "BLOCKED"),
        "research_only": True,
        "can_confirm_signal": False,
        "trading_authority": False,
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False,
        "provider_requests": 0,
        "provider_to_radar_e2e": "NOT_VERIFIED",
        "reasons": full.get("reasons") or [],
        "observed_at_utc": full.get("observed_at_utc"),
    }
    provenance = full.get("provenance") or {}
    common["source"] = {
        "repo_sha": provenance.get("market_repo_sha"),
        "runtime_instance_id": provenance.get("market_runtime_instance_id"),
        "sequence": provenance.get("market_sequence"),
        "market_emitted_at_utc": provenance.get("market_emitted_at_utc"),
        "market_age_seconds": provenance.get("market_age_seconds"),
        "radar_age_seconds": provenance.get("radar_age_seconds"),
        "radar_poll_status": provenance.get("radar_poll_status"),
        "bar_closure": provenance.get("source_bar_closure"),
        "delivery_mode": provenance.get("source_delivery_mode"),
    }
    if full.get("ok") is not True or full.get("status") != "ALIGNED_RESEARCH_ONLY":
        return {
            **common, "ok": False, "symbols": {},
            "missing_symbols": full.get("missing_symbols") or [],
            "read_latency_ms": round((perf_counter() - started) * 1000, 3),
        }

    def compact_bar(value: object) -> dict | None:
        if not isinstance(value, dict):
            return None
        return {
            key: value.get(key) for key in (
                "close", "bar_end_utc", "is_closed", "is_complete", "quality_flags"
            )
        }

    result = {}
    for symbol, item in full["symbols"].items():
        frames = item.get("multitimeframe") or {}
        bars = item.get("latest_bars") or {}
        result[symbol] = {
            "bars": {tf: compact_bar(bars.get(tf)) for tf in ("1m", "5m", "15m", "1h")},
            "trend": {
                name: {
                    "trend": (frames.get(key) or {}).get("trend"),
                    "quality": ((frames.get(key) or {}).get("quality") or {}).get("status"),
                    "partial": ((frames.get(key) or {}).get("quality") or {}).get("is_partial_bar"),
                }
                for name, key in (("daily", "daily"), ("hourly", "hourly"), ("15m", "intraday_15m"))
            },
            "alignment": frames.get("alignment"),
            "research_score": frames.get("research_score"),
            "risk_flags": frames.get("risk_flags") or [],
            "watch_conditions": frames.get("watch_conditions") or [],
            "support_levels": (frames.get("structure") or {}).get("support_levels"),
            "resistance_levels": (frames.get("structure") or {}).get("resistance_levels"),
            "volume_confirmation": (frames.get("structure") or {}).get("volume_confirmation"),
            "technical_as_of": item.get("technical_as_of"),
            "signal_permission": "BLOCKED",
        }
    return {
        **common, "symbols": result,
        "read_latency_ms": round((perf_counter() - started) * 1000, 3),
    }

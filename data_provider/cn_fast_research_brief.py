"""One-call, small, fail-closed CN market + precomputed Radar preview.

Reads existing qualified cache readers only. No provider requests, model calls,
new trading decisions, broker mutations, or implied closed-bar guarantees.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from time import perf_counter
from typing import Iterable

from data_provider.cn_cloud_runtime_reader import read_cn_market_data
from data_provider.cn_radar_runtime_reader import read_cn_radar_analysis

_MAX_SYMBOLS = 8
_FRAMES = ("1d", "60m", "15m")
_PROVIDERS = frozenset(("eastmoney", "tencent", "tickflow"))


def _short_labels(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item[:96] for item in value[:3] if isinstance(item, str)]


def _finite_number(value: object) -> float | None:
    return float(value) if type(value) in (int, float) and isfinite(value) else None


def _symbol(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if code.endswith(suffix):
            code = code[:-3]
            break
    return code if len(code) == 6 and code.isdigit() else None


def read_cn_quick_scan(
    symbols: Iterable[str] | None = None,
    *,
    radar_path: str | None = None,
    snapshot_path: str | None = None,
    now_utc: datetime | None = None,
) -> dict:
    """Research preview for ChatGPT/UI's first useful response.

    A quick cache read never proves delivery latency or source admission. Keep
    original producer's analysis time distinct from this reader's elapsed time.
    """
    started = perf_counter()
    safety = {
        "schema": "stock_razor_cn_quick_scan_v0_1",
        "research_only": True,
        "can_confirm_signal": False,
        "trading_authority": False,
        "entry_gate": "ENTRY_BLOCKED",
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "paper_auto_ready": False,
        "live_trade": False,
        "trade_execution": False,
        "provider_requests": 0,
        "model_inference_performed": False,
    }

    def finish(status: str, *, reasons: list[str], result: dict | None = None,
               provenance: dict | None = None, radar_analysis_ms: float | None = None) -> dict:
        return {
            **safety,
            "ok": status == "RESEARCH_ONLY",
            "status": status,
            "reasons": reasons,
            "symbols": result or {},
            "source": provenance or {},
            "performance": {
                "reader_total_ms": round((perf_counter() - started) * 1000, 3),
                "radar_analysis_ms": radar_analysis_ms,
                "data_fetch_ms": None,
                "chatgpt_analysis_ms": None,
                "user_visible_total_ms": None,
                "provider_to_receiver_lag_ms": None,
            },
        }

    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        return finish("INVALID_ARGUMENT", reasons=["INVALID_CLOCK"])
    now = now.astimezone(timezone.utc)

    if symbols is not None:
        if isinstance(symbols, (str, bytes)):
            return finish("INVALID_ARGUMENT", reasons=["INVALID_SYMBOL_LIST"])
        try:
            values = list(symbols)
        except TypeError:
            return finish("INVALID_ARGUMENT", reasons=["INVALID_SYMBOL_LIST"])
        if not 1 <= len(values) <= _MAX_SYMBOLS:
            return finish("INVALID_ARGUMENT", reasons=["INVALID_SYMBOL_COUNT"])
        selected = tuple(dict.fromkeys(_symbol(v) for v in values))
        if None in selected:
            return finish("INVALID_ARGUMENT", reasons=["INVALID_SYMBOL"])
    else:
        selected = ()

    try:
        radar = read_cn_radar_analysis(
            list(selected) if selected else None, path=radar_path, now_utc=now,
        )
    except (OSError, ValueError, TypeError, RuntimeError):
        return finish("BLOCKED", reasons=["RADAR_READER_ERROR"])
    if not isinstance(radar, dict):
        return finish("BLOCKED", reasons=["RADAR_READER_INVALID"])
    if not (
        radar.get("research_only") is True
        and radar.get("can_confirm_signal") is False
        and radar.get("radar_admission") == "BLOCKED"
        and radar.get("live_trade") is False
    ):
        return finish("BLOCKED", reasons=["RADAR_NOT_QUALIFIED"])
    if radar.get("ok") is not True or radar.get("status") != "PASS":
        return finish("BLOCKED", reasons=["RADAR_NOT_FRESH"])
    if radar.get("poll_status") not in {"PASS", "UNCHANGED"}:
        return finish("BLOCKED", reasons=["RADAR_POLL_INVALID"])
    radar_symbols = radar.get("symbols")
    if not isinstance(radar_symbols, dict):
        return finish("BLOCKED", reasons=["RADAR_SYMBOLS_INVALID"])

    selected = selected or tuple(sorted(radar_symbols)[:_MAX_SYMBOLS])
    if not selected or any(s not in radar_symbols for s in selected):
        return finish("BLOCKED", reasons=["SYMBOL_EVIDENCE_INCOMPLETE"])
    expected_identity = (
        radar.get("source_repo_sha"),
        radar.get("source_runtime_instance_id"),
        radar.get("source_sequence"),
        radar.get("source_emitted_at_utc"),
    )
    if not (
        isinstance(expected_identity[0], str) and len(expected_identity[0]) == 40
        and all(c in "0123456789abcdef" for c in expected_identity[0])
        and isinstance(expected_identity[1], str) and expected_identity[1]
        and type(expected_identity[2]) is int and expected_identity[2] >= 0
        and isinstance(expected_identity[3], str) and expected_identity[3]
    ):
        return finish("BLOCKED", reasons=["SOURCE_IDENTITY_MISSING"])

    output = {}
    ages = []
    for symbol in selected:
        studied = radar_symbols[symbol]
        if not (
            isinstance(studied, dict)
            and studied.get("research_only") is True
            and studied.get("can_confirm_signal") is False
            and studied.get("signal_permission") == "record_only"
        ):
            return finish("BLOCKED", reasons=["RADAR_SYMBOL_NOT_QUALIFIED"])
        frames = {}
        for timeframe in _FRAMES:
            try:
                market = read_cn_market_data(
                    symbol, timeframe=timeframe, limit=1,
                    path=snapshot_path, now_utc=now,
                )
            except (OSError, ValueError, TypeError, RuntimeError):
                return finish("BLOCKED", reasons=["SOURCE_READER_ERROR"])
            if not isinstance(market, dict) or not (
                market.get("ok") is True and market.get("status") == "PASS"
                and market.get("research_only") is True
                and market.get("radar_admission") == "BLOCKED"
                and market.get("live_trade") is False
            ):
                return finish("BLOCKED", reasons=["MARKET_NOT_FRESH_AND_VALID"])
            identity = (
                market.get("repo_sha"), market.get("runtime_instance_id"),
                market.get("sequence"), market.get("emitted_at_utc"),
            )
            if identity != expected_identity:
                return finish("BLOCKED", reasons=["SOURCE_IDENTITY_MISMATCH"])
            if market.get("provider_used") not in _PROVIDERS:
                return finish("BLOCKED", reasons=["PROVIDER_UNKNOWN"])
            rows = market.get("rows")
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                return finish("BLOCKED", reasons=["MISSING_BAR"])
            age = market.get("source_age_seconds")
            if type(age) not in (int, float) or not 0 <= age <= 180:
                return finish("BLOCKED", reasons=["SOURCE_AGE_INVALID"])
            ages.append(age)
            latest = rows[-1]
            # Bar finality is not established by a source label or currentness
            # flag alone. The concise report must not manufacture a CLOSED bar.
            frames[timeframe] = {
                "label": latest.get("label")[:32] if isinstance(latest.get("label"), str) else None,
                "close": _finite_number(latest.get("close")),
                "provider": market["provider_used"],
                "fallback": market.get("fallback_from"),
                "bar_status": "UNKNOWN",
                "timestamp_semantic": market.get("timestamp_semantic", "UNKNOWN"),
                "currentness": market.get("currentness", "UNPROVEN"),
            }
        technical = studied.get("technical")
        technical = technical if isinstance(technical, dict) else {}
        output[symbol] = {
            "frames": frames,
            "research_score": _finite_number(technical.get("research_score")),
            "alignment": technical.get("alignment")[:48] if isinstance(technical.get("alignment"), str) else None,
            "risk_flags": _short_labels(technical.get("risk_flags")),
            "watch_conditions": _short_labels(technical.get("watch_conditions")),
            "signal_permission": "BLOCKED",
        }
    radar_ms = radar.get("radar_analysis_latency_ms")
    radar_ms = radar_ms if type(radar_ms) in (int, float) and radar_ms >= 0 else None
    source = {
        "reader_kind": "LOCAL_CACHE_READ",
        "repo_sha": expected_identity[0],
        "runtime_instance_id": expected_identity[1],
        "sequence": expected_identity[2],
        "source_emitted_at_utc": expected_identity[3],
        "observed_at_utc": now.isoformat(),
        "market_age_seconds": max(ages),
        "radar_age_seconds": radar.get("source_age_seconds"),
    }
    return finish("RESEARCH_ONLY",
                  reasons=["BAR_FINALITY_UNVERIFIED", "SIGNAL_AND_TRADING_ADMISSION_BLOCKED"],
                  result=output, provenance=source, radar_analysis_ms=radar_ms)



def build_cn_main_control_report_v41(
    symbol: str,
    endpoint_evidence: dict | None = None,
    *,
    holdings: list[dict] | None = None,
    opportunities: list[dict] | None = None,
    conditional_plans: list[dict] | None = None,
    timings: dict | None = None,
    received_at_utc: str | None = None,
    report_completed_at_utc: str | None = None,
    feedback_hub: object | None = None,
) -> dict:
    """Assemble the V4.1 Main Control report from independent endpoint evidence.

    This adapter performs no provider I/O. Missing or invalid evidence is
    returned as BLOCKED by the shared V4.1 contract.
    """
    from data_provider.radar_report_v41 import build_report

    report = build_report(
        "CN", symbol, endpoint_evidence, holdings=holdings,
        opportunities=opportunities, conditional_plans=conditional_plans,
        timings=timings, received_at_utc=received_at_utc,
        report_completed_at_utc=report_completed_at_utc,
    )
    if feedback_hub is not None:
        from data_provider.radar_report_v41 import submit_report_feedback

        submit_report_feedback(report, feedback_hub)
    return report

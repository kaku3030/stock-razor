"""Research-only technical evaluation for cloud A-share observations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import math
from typing import Mapping

import pandas as pd

from src.technical.models import TimeframeState
from src.technical.technical_analyzer import TechnicalAnalyzer


CN_OBSERVATION_SCHEMA = "stock_razor_cn_eastmoney_observation_v1"
CN_RADAR_SCHEMA = "stock_razor_cn_radar_research_v1"
SUPPORTED_FRAMES = ("1d", "60m", "15m")
STRUCTURAL_FLAGS = frozenset(
    {"NON_POSITIVE_PRICE", "INVALID_OHLC", "NEGATIVE_VOLUME", "NEGATIVE_AMOUNT"}
)


class CnObservationAnalysisError(ValueError):
    pass


def _parse_iso(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CnObservationAnalysisError(f"{field_name} missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CnObservationAnalysisError(f"{field_name} invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CnObservationAnalysisError(f"{field_name} must be timezone-aware")
    return parsed


def _finite(value: object, *, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CnObservationAnalysisError(f"{field_name} must be numeric") from exc
    if not math.isfinite(number):
        raise CnObservationAnalysisError(f"{field_name} must be finite")
    return number


def _frame(item: Mapping[str, object], timeframe: str) -> tuple[pd.DataFrame, dict]:
    frames = item.get("timeframes")
    if not isinstance(frames, Mapping):
        raise CnObservationAnalysisError("symbol timeframes missing")
    frame = frames.get(timeframe)
    if not isinstance(frame, Mapping):
        raise CnObservationAnalysisError(f"{timeframe} frame missing")
    if frame.get("status") != "PASS":
        raise CnObservationAnalysisError(f"{timeframe} frame not PASS")
    rows = frame.get("rows")
    if not isinstance(rows, list) or not rows:
        raise CnObservationAnalysisError(f"{timeframe} rows missing")

    records: list[dict] = []
    previous: pd.Timestamp | None = None
    severe: list[str] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise CnObservationAnalysisError(f"{timeframe}[{index}] invalid")
        label = str(raw.get("label") or "").strip()
        if not label:
            raise CnObservationAnalysisError(f"{timeframe}[{index}].label missing")
        stamp = pd.to_datetime(label, errors="coerce")
        if pd.isna(stamp):
            raise CnObservationAnalysisError(f"{timeframe}[{index}].label invalid")
        if previous is not None and stamp <= previous:
            raise CnObservationAnalysisError(f"{timeframe} labels not strictly increasing")
        previous = stamp

        open_ = _finite(raw.get("open"), field_name=f"{timeframe}[{index}].open")
        high = _finite(raw.get("high"), field_name=f"{timeframe}[{index}].high")
        low = _finite(raw.get("low"), field_name=f"{timeframe}[{index}].low")
        close = _finite(raw.get("close"), field_name=f"{timeframe}[{index}].close")
        volume = _finite(
            raw.get("volume_raw"),
            field_name=f"{timeframe}[{index}].volume_raw",
        )
        if min(open_, high, low, close) <= 0:
            severe.append("NON_POSITIVE_PRICE")
        if high < max(open_, close, low) or low > min(open_, close, high):
            severe.append("INVALID_OHLC")
        if volume < 0:
            severe.append("NEGATIVE_VOLUME")
        flags = raw.get("quality_flags") or []
        if isinstance(flags, list):
            severe.extend(
                str(flag).strip().upper()
                for flag in flags
                if str(flag).strip().upper() in STRUCTURAL_FLAGS
            )
        records.append(
            {
                "date": stamp,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    if severe:
        raise CnObservationAnalysisError(
            f"{timeframe} structural flags: {','.join(dict.fromkeys(severe))}"
        )

    provenance = {
        "provider_used": frame.get("provider_used"),
        "provider_lineage": frame.get("provider_lineage"),
        "fallback_from": frame.get("fallback_from"),
        "fallback_reason": frame.get("fallback_reason"),
        "timestamp_semantic": frame.get("timestamp_semantic"),
        "currentness": frame.get("currentness"),
        "row_count": len(records),
        "latest_label": rows[-1].get("label"),
        "volume_unit": rows[-1].get("volume_unit"),
    }
    return pd.DataFrame(records), provenance


def _mark_intraday_unproven(state: TimeframeState, timeframe: str) -> TimeframeState:
    warnings = list(
        dict.fromkeys(
            [
                *state.quality.warnings,
                f"{timeframe}_timestamp_semantics_unproven",
                f"{timeframe}_currentness_unproven",
            ]
        )
    )
    quality = replace(
        state.quality,
        status="partial" if state.quality.status != "missing" else state.quality.status,
        warnings=warnings,
    )
    return replace(
        state,
        confidence=min(state.confidence, 0.65),
        quality=quality,
    )


def evaluate_cn_observation_payload(
    payload: Mapping[str, object],
    *,
    analyzer: TechnicalAnalyzer | None = None,
) -> dict:
    """Evaluate A-share daily/60m/15m observations without promoting currentness."""

    if payload.get("schema") != CN_OBSERVATION_SCHEMA:
        raise CnObservationAnalysisError("unsupported CN observation schema")
    if not (
        payload.get("research_only") is True
        and payload.get("can_confirm_signal") is False
        and payload.get("radar_admission") == "BLOCKED"
        and payload.get("live_trade") is False
        and payload.get("intraday_timestamp_semantics_proven") is False
        and payload.get("intraday_currentness_proven") is False
    ):
        raise CnObservationAnalysisError("CN observation safety contract violation")

    repo_sha = str(payload.get("repo_sha") or "").strip().lower()
    if len(repo_sha) != 40 or any(ch not in "0123456789abcdef" for ch in repo_sha):
        raise CnObservationAnalysisError("repo_sha invalid")
    runtime_instance_id = str(payload.get("runtime_instance_id") or "").strip()
    if not runtime_instance_id:
        raise CnObservationAnalysisError("runtime_instance_id missing")
    try:
        sequence = int(payload.get("sequence"))
    except (TypeError, ValueError) as exc:
        raise CnObservationAnalysisError("sequence invalid") from exc
    if sequence <= 0:
        raise CnObservationAnalysisError("sequence invalid")
    emitted_at = _parse_iso(payload.get("emitted_at_utc"), field_name="emitted_at_utc")

    symbols = payload.get("symbols")
    if not isinstance(symbols, Mapping) or not symbols:
        raise CnObservationAnalysisError("symbols missing")

    technical_analyzer = analyzer or TechnicalAnalyzer()
    results: dict[str, dict] = {}
    for raw_symbol in sorted(symbols):
        symbol = str(raw_symbol).strip().upper()
        item = symbols[raw_symbol]
        if not isinstance(item, Mapping):
            results[symbol] = {
                "status": "BLOCKED",
                "reasons": ["SYMBOL_PAYLOAD_INVALID"],
                "research_only": True,
                "can_confirm_signal": False,
            }
            continue
        if not (
            item.get("status") == "PASS"
            and item.get("radar_admission") == "BLOCKED"
            and item.get("live_trade") is False
        ):
            results[symbol] = {
                "status": "BLOCKED",
                "reasons": ["SYMBOL_SOURCE_NOT_PASS"],
                "research_only": True,
                "can_confirm_signal": False,
            }
            continue
        try:
            daily, daily_prov = _frame(item, "1d")
            hourly, hourly_prov = _frame(item, "60m")
            intraday, intraday_prov = _frame(item, "15m")
            technical = technical_analyzer.analyze(
                symbol,
                daily,
                hourly,
                intraday,
                hourly_partial=False,
                intraday_partial=False,
            )
            technical.hourly = _mark_intraday_unproven(technical.hourly, "1h")
            technical.intraday = _mark_intraday_unproven(technical.intraday, "15m")
            technical.risk_flags = list(
                dict.fromkeys(
                    [
                        *technical.risk_flags,
                        "cn_intraday_timestamp_semantics_unproven",
                        "cn_intraday_currentness_unproven",
                    ]
                )
            )
            results[symbol] = {
                "status": "RESEARCH_STATE",
                "technical": technical.to_dict(),
                "frame_provenance": {
                    "1d": daily_prov,
                    "60m": hourly_prov,
                    "15m": intraday_prov,
                },
                "providers_used": item.get("providers_used") or [],
                "provider_policy": item.get("provider_policy"),
                "research_only": True,
                "can_confirm_signal": False,
                "signal_permission": "record_only",
            }
        except Exception as exc:
            results[symbol] = {
                "status": "BLOCKED",
                "reasons": [f"ANALYSIS_ERROR:{type(exc).__name__}"],
                "research_only": True,
                "can_confirm_signal": False,
            }

    research_symbols = [
        symbol for symbol, item in results.items()
        if item.get("status") == "RESEARCH_STATE"
    ]
    status = "PASS" if len(research_symbols) == len(results) else (
        "PARTIAL" if research_symbols else "BLOCKED"
    )
    return {
        "schema": CN_RADAR_SCHEMA,
        "source_repo_sha": repo_sha,
        "source_runtime_instance_id": runtime_instance_id,
        "source_sequence": sequence,
        "source_emitted_at_utc": emitted_at.isoformat(),
        "status": status,
        "symbols": results,
        "research_state_symbols": research_symbols,
        "provider_policy": payload.get("provider_policy"),
        "provider_lineages": payload.get("provider_lineages") or [],
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }

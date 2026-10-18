"""Research-only technical evaluation for cloud A-share observations."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import math
from typing import Mapping
from zoneinfo import ZoneInfo

import pandas as pd

from src.services.a_share_intraday_currentness import (
    qualify_same_session_currentness,
)
from src.services.a_share_intraday_semantics import CN_MARKET_TIMEZONE, TimestampSemantic
from src.technical.models import TimeframeState
from src.technical.technical_analyzer import TechnicalAnalyzer
from data_provider.cn_tickflow_research_cache import (
    _vendor_etf_tick_lattice_shape_valid, _vendor_ohlc_float_gap_bucket,
)


CN_OBSERVATION_SCHEMA = "stock_razor_cn_eastmoney_observation_v1"
TICKFLOW_RADAR_INPUT_SCHEMA = "stock_razor_cn_tickflow_radar_input_v0_1"
CN_RADAR_SCHEMA = "stock_razor_cn_radar_research_v1"
SUPPORTED_FRAMES = ("1d", "60m", "15m")
STRUCTURAL_FLAGS = frozenset(
    {"NON_POSITIVE_PRICE", "INVALID_OHLC", "NEGATIVE_VOLUME", "NEGATIVE_AMOUNT"}
)
OPENING_AUCTION_RANGE_GAP = "OPENING_AUCTION_RANGE_GAP"
_OPENING_BAR_SUFFIX = {"15m": "09:45", "60m": "10:30"}


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


def _is_tencent_opening_auction_range_gap(
    raw: Mapping[str, object],
    *,
    timeframe: str,
    label: str,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> bool:
    """Recognize the Tencent A-share opening-auction aggregate edge case."""

    suffix = _OPENING_BAR_SUFFIX.get(timeframe)
    return bool(
        str(raw.get("provider") or "").strip().lower() == "tencent"
        and suffix is not None
        and label.endswith(suffix)
        and high >= low
        and low <= close <= high
        and not (low <= open_ <= high)
    )


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
    soft_warnings: list[str] = []
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
        opening_gap = _is_tencent_opening_auction_range_gap(
            raw,
            timeframe=timeframe,
            label=label,
            open_=open_,
            high=high,
            low=low,
            close=close,
        )
        if min(open_, high, low, close) <= 0:
            severe.append("NON_POSITIVE_PRICE")
        if high < max(open_, close, low) or low > min(open_, close, high):
            if opening_gap:
                soft_warnings.append(OPENING_AUCTION_RANGE_GAP)
            elif (
                frame.get("provider_used") == "TICKFLOW_PREMIUM"
                and raw.get("ohlc_validation") == "VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
                and _vendor_ohlc_float_gap_bucket(open_, high, low, close) == "WITHIN_1E_MINUS_5"
                and _vendor_etf_tick_lattice_shape_valid(open_, high, low, close)
            ):
                soft_warnings.append("VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY")
            else:
                severe.append("INVALID_OHLC")
        if volume < 0:
            severe.append("NEGATIVE_VOLUME")
        flags = raw.get("quality_flags") or []
        if isinstance(flags, list):
            for flag in flags:
                normalized = str(flag).strip().upper()
                if normalized == "INVALID_OHLC" and opening_gap:
                    soft_warnings.append(OPENING_AUCTION_RANGE_GAP)
                elif normalized in STRUCTURAL_FLAGS:
                    severe.append(normalized)
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
        "analysis_warnings": list(dict.fromkeys(soft_warnings)),
    }
    if frame.get("provider_used") == "TICKFLOW_PREMIUM":
        provenance.update(
            source_symbol=frame.get("source_symbol"),
            bar_finality="NOT_VERIFIED", adjustment="NOT_VERIFIED",
        )
    return pd.DataFrame(records), provenance


def _quarantine_unverified_daily_date(
    frame: pd.DataFrame,
    provenance: dict,
    *,
    observed_at: datetime,
) -> tuple[pd.DataFrame, dict]:
    """Exclude today's / future DAILY_DATE labels from D1 indicators.

    Exchange-local midnight is a date label, not evidence that today's
    Shanghai session has closed. Even at 15:02, do not promote it without
    independent provider finality. Yesterday's historical rows remain
    usable for research; no change to any trade admission gate.
    """
    today = observed_at.astimezone(ZoneInfo(CN_MARKET_TIMEZONE)).date()
    stamps = frame["date"]
    if getattr(stamps.dt, "tz", None) is not None:
        stamps = stamps.dt.tz_convert(CN_MARKET_TIMEZONE).dt.tz_localize(None)
    kept = frame.loc[stamps.dt.date < today].copy()
    excluded = len(frame) - len(kept)
    if excluded == 0:
        return frame, provenance
    if kept.empty:
        raise CnObservationAnalysisError("1d no prior-session historical bars")
    updated = dict(provenance)
    updated["analysis_row_count"] = len(kept)
    updated["unverified_daily_date_rows_excluded"] = excluded
    updated["analysis_warnings"] = list(dict.fromkeys([
        *provenance.get("analysis_warnings", []),
        "CURRENT_OR_FUTURE_DAILY_DATE_EXCLUDED",
    ]))
    return kept, updated


def _quarantine_future_intraday_labels(
    frame: pd.DataFrame,
    provenance: dict,
    *,
    timeframe: str,
    observed_at: datetime,
) -> tuple[pd.DataFrame, dict]:
    """Exclude provider-labeled bars later than the observation clock.

    Such a bar might be a BAR_END-labeled forming candle. Without qualified
    timestamp semantics, it must not influence research indicators or become
    an implicit closed-bar fact. Historical valid rows are retained.
    """
    clock = observed_at.astimezone(ZoneInfo(CN_MARKET_TIMEZONE)).replace(tzinfo=None)
    stamps = frame["date"]
    # Preserve the existing naive Shanghai-local label contract; offset-aware
    # provider labels are converted to the market clock before comparison.
    if getattr(stamps.dt, "tz", None) is not None:
        stamps = stamps.dt.tz_convert(CN_MARKET_TIMEZONE).dt.tz_localize(None)
    kept = frame.loc[stamps <= pd.Timestamp(clock)].copy()
    excluded = len(frame) - len(kept)
    if not excluded:
        return frame, provenance
    if kept.empty:
        raise CnObservationAnalysisError(f"{timeframe} has no nonfuture bars")
    revised = dict(provenance)
    revised["analysis_row_count"] = len(kept)
    revised["future_labeled_rows_excluded"] = excluded
    revised["analysis_warnings"] = list(dict.fromkeys([
        *provenance.get("analysis_warnings", []),
        "FUTURE_PROVIDER_LABEL_EXCLUDED",
    ]))
    return kept, revised


def _qualified_intraday_bar_end(item: Mapping[str, object]) -> bool:
    """Validate symbol-level BAR_END evidence instead of trusting one boolean."""

    claim = item.get("intraday_timestamp_semantics_proven")
    if claim is False or claim is None:
        return False
    if claim is not True:
        raise CnObservationAnalysisError(
            "symbol intraday_timestamp_semantics_proven must be boolean"
        )
    frames = item.get("timeframes")
    if not isinstance(frames, Mapping):
        raise CnObservationAnalysisError("symbol timeframes missing")
    for timeframe in ("60m", "15m"):
        frame = frames.get(timeframe)
        if not isinstance(frame, Mapping):
            raise CnObservationAnalysisError(f"{timeframe} frame missing")
        qualification = frame.get("timestamp_qualification")
        if not (
            frame.get("status") == "PASS"
            and frame.get("timestamp_semantic") == "BAR_END"
            and frame.get("currentness") in {"UNPROVEN", "PROVEN"}
            and isinstance(qualification, Mapping)
            and qualification.get("status") == "PASS"
            and qualification.get("timestamp_semantic") == "BAR_END"
            and qualification.get("currentness_proven") is False
            and qualification.get("radar_admission") == "BLOCKED"
            and qualification.get("live_trade") is False
        ):
            raise CnObservationAnalysisError(
                f"{timeframe} BAR_END qualification evidence invalid"
            )
    return True


def _qualified_intraday_currentness(
    item: Mapping[str, object],
    *,
    observed_at: datetime,
) -> bool:
    """Recompute deterministic same-session Currentness from source evidence."""

    claim = item.get("intraday_currentness_proven")
    if not isinstance(claim, bool):
        raise CnObservationAnalysisError(
            "symbol intraday_currentness_proven must be boolean"
        )
    frames = item.get("timeframes")
    if not isinstance(frames, Mapping):
        raise CnObservationAnalysisError("symbol timeframes missing")

    proven: list[bool] = []
    for timeframe in ("60m", "15m"):
        frame = frames.get(timeframe)
        if not isinstance(frame, Mapping):
            raise CnObservationAnalysisError(f"{timeframe} frame missing")
        currentness = frame.get("currentness")
        if currentness not in {"UNPROVEN", "PROVEN"}:
            raise CnObservationAnalysisError(
                f"{timeframe} currentness claim invalid"
            )

        if frame.get("timestamp_semantic") != "BAR_END":
            if currentness != "UNPROVEN":
                raise CnObservationAnalysisError(
                    f"{timeframe} cannot prove Currentness without BAR_END"
                )
            proven.append(False)
            continue

        evidence = frame.get("currentness_qualification")
        if evidence is None:
            # Backward-compatible rolling deployment: pre-wiring BAR_END
            # observations remain explicitly UNPROVEN.
            if currentness != "UNPROVEN":
                raise CnObservationAnalysisError(
                    f"{timeframe} missing Currentness evidence"
                )
            proven.append(False)
            continue
        if not isinstance(evidence, Mapping):
            raise CnObservationAnalysisError(
                f"{timeframe} Currentness evidence invalid"
            )

        rows = frame.get("rows")
        if not isinstance(rows, list) or not rows or not isinstance(rows[-1], Mapping):
            raise CnObservationAnalysisError(
                f"{timeframe} rows missing for Currentness verification"
            )
        expected = qualify_same_session_currentness(
            str(rows[-1].get("label") or ""),
            interval_minutes=int(timeframe[:-1]),
            timestamp_semantic=TimestampSemantic.BAR_END,
            observed_at=observed_at,
        )
        if dict(evidence) != expected.to_dict():
            raise CnObservationAnalysisError(
                f"{timeframe} Currentness evidence mismatch"
            )
        frame_proven = expected.currentness_proven
        if (currentness == "PROVEN") is not frame_proven:
            raise CnObservationAnalysisError(
                f"{timeframe} Currentness claim/evidence mismatch"
            )
        proven.append(frame_proven)

    evaluated = all(proven)
    if claim is not evaluated:
        raise CnObservationAnalysisError(
            "symbol intraday_currentness_proven claim/evidence mismatch"
        )
    return evaluated


def _mark_intraday_unproven(
    state: TimeframeState,
    timeframe: str,
    *,
    timestamp_semantics_proven: bool,
) -> TimeframeState:
    warnings = list(
        dict.fromkeys(
            [
                *state.quality.warnings,
                *(
                    []
                    if timestamp_semantics_proven
                    else [f"{timeframe}_timestamp_semantics_unproven"]
                ),
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
    """Evaluate A-share observations while keeping Currentness non-actionable."""

    if payload.get("schema") not in {CN_OBSERVATION_SCHEMA, TICKFLOW_RADAR_INPUT_SCHEMA}:
        raise CnObservationAnalysisError("unsupported CN observation schema")
    root_timestamp_semantics_proven = payload.get(
        "intraday_timestamp_semantics_proven"
    )
    root_currentness_proven = payload.get("intraday_currentness_proven")
    if not isinstance(root_timestamp_semantics_proven, bool):
        raise CnObservationAnalysisError(
            "intraday_timestamp_semantics_proven must be boolean"
        )
    if not isinstance(root_currentness_proven, bool):
        raise CnObservationAnalysisError(
            "intraday_currentness_proven must be boolean"
        )
    if not (
        payload.get("research_only") is True
        and payload.get("can_confirm_signal") is False
        and payload.get("radar_admission") == "BLOCKED"
        and payload.get("live_trade") is False
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
            daily, daily_prov = _quarantine_unverified_daily_date(
                daily, daily_prov, observed_at=emitted_at,
            )
            hourly, hourly_prov = _frame(item, "60m")
            intraday, intraday_prov = _frame(item, "15m")
            hourly, hourly_prov = _quarantine_future_intraday_labels(
                hourly, hourly_prov, timeframe="60m", observed_at=emitted_at,
            )
            intraday, intraday_prov = _quarantine_future_intraday_labels(
                intraday, intraday_prov, timeframe="15m", observed_at=emitted_at,
            )
            timestamp_semantics_proven = _qualified_intraday_bar_end(item)
            if root_timestamp_semantics_proven and not timestamp_semantics_proven:
                raise CnObservationAnalysisError(
                    "root BAR_END claim is not supported by symbol evidence"
                )
            currentness_proven = _qualified_intraday_currentness(
                item,
                observed_at=emitted_at,
            )
            if root_currentness_proven and not currentness_proven:
                raise CnObservationAnalysisError(
                    "root Currentness claim is not supported by symbol evidence"
                )
            technical = technical_analyzer.analyze(
                symbol,
                daily,
                hourly,
                intraday,
                hourly_partial=payload.get("schema") == TICKFLOW_RADAR_INPUT_SCHEMA,
                intraday_partial=payload.get("schema") == TICKFLOW_RADAR_INPUT_SCHEMA,
            )
            if not currentness_proven:
                technical.hourly = _mark_intraday_unproven(
                    technical.hourly,
                    "1h",
                    timestamp_semantics_proven=timestamp_semantics_proven,
                )
                technical.intraday = _mark_intraday_unproven(
                    technical.intraday,
                    "15m",
                    timestamp_semantics_proven=timestamp_semantics_proven,
                )
            provenance_warnings = {
                warning
                for provenance in (daily_prov, hourly_prov, intraday_prov)
                for warning in provenance.get("analysis_warnings", [])
            }
            technical.risk_flags = list(
                dict.fromkeys(
                    [
                        *technical.risk_flags,
                        *(
                            ["cn_current_or_future_daily_date_unverified"]
                            if "CURRENT_OR_FUTURE_DAILY_DATE_EXCLUDED" in provenance_warnings
                            else []
                        ),
                        *(
                            []
                            if timestamp_semantics_proven
                            else ["cn_intraday_timestamp_semantics_unproven"]
                        ),
                        *(
                            []
                            if currentness_proven
                            else ["cn_intraday_currentness_unproven"]
                        ),
                        *(
                            ["cn_opening_auction_range_gap"]
                            if OPENING_AUCTION_RANGE_GAP in provenance_warnings
                            else []
                        ),
                        *(
                            ["cn_future_labeled_intraday_bar_quarantined"]
                            if "FUTURE_PROVIDER_LABEL_EXCLUDED" in provenance_warnings
                            else []
                        ),
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
                "intraday_timestamp_semantics_proven": timestamp_semantics_proven,
                "intraday_currentness_proven": currentness_proven,
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
    evaluated_timestamp_semantics_proven = bool(research_symbols) and (
        len(research_symbols) == len(results)
        and all(
            results[symbol].get("intraday_timestamp_semantics_proven") is True
            for symbol in research_symbols
        )
    )
    evaluated_currentness_proven = bool(research_symbols) and (
        len(research_symbols) == len(results)
        and all(
            results[symbol].get("intraday_currentness_proven") is True
            for symbol in research_symbols
        )
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
        "intraday_timestamp_semantics_proven": evaluated_timestamp_semantics_proven,
        "intraday_currentness_proven": evaluated_currentness_proven,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }

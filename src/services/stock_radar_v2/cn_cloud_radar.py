"""Isolated research evaluator for cloud A-share observation data."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Mapping

import pandas as pd

from src.technical.models import DataQuality, TimeframeState
from src.technical.technical_analyzer import TechnicalAnalyzer


SCHEMA = "stock_razor_cn_eastmoney_observation_v1"
ACTIVE_MAX_AGE_SECONDS = 180
TIMEFRAMES = ("1d", "60m", "15m")


@dataclass(frozen=True)
class CNCloudRadarEvaluation:
    status: str
    source_repo_sha: str | None
    source_runtime_instance_id: str | None
    source_sequence: int | None
    source_emitted_at_utc: str | None
    symbols: tuple[dict, ...] = ()
    reasons: tuple[str, ...] = ()
    research_only: bool = True
    can_confirm_signal: bool = False
    radar_admission: str = "BLOCKED"
    live_trade: bool = False

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "source_repo_sha": self.source_repo_sha,
            "source_runtime_instance_id": self.source_runtime_instance_id,
            "source_sequence": self.source_sequence,
            "source_emitted_at_utc": self.source_emitted_at_utc,
            "symbols": [dict(item) for item in self.symbols],
            "reasons": list(self.reasons),
            "research_only": True,
            "can_confirm_signal": False,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }


class CNCloudRadarEvaluator:
    """Compute neutral daily/60m/15m state from one cloud observation snapshot."""

    def __init__(
        self,
        analyzer: TechnicalAnalyzer | None = None,
        *,
        max_age_seconds: int = ACTIVE_MAX_AGE_SECONDS,
    ) -> None:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        self._analyzer = analyzer or TechnicalAnalyzer()
        self._max_age_seconds = int(max_age_seconds)

    def evaluate_file(
        self,
        path: str | Path,
        *,
        expected_repo_sha: str,
        now_utc: datetime | None = None,
    ) -> CNCloudRadarEvaluation:
        try:
            with Path(path).open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception as exc:
            return self._blocked(None, f"SOURCE_INVALID:{type(exc).__name__}")
        return self.evaluate_payload(
            payload,
            expected_repo_sha=expected_repo_sha,
            now_utc=now_utc,
        )

    def evaluate_payload(
        self,
        payload: object,
        *,
        expected_repo_sha: str,
        now_utc: datetime | None = None,
    ) -> CNCloudRadarEvaluation:
        expected = str(expected_repo_sha or "").strip().lower()
        if len(expected) != 40 or any(ch not in "0123456789abcdef" for ch in expected):
            raise ValueError("expected_repo_sha must be an exact 40-character git SHA")
        if not isinstance(payload, Mapping):
            return self._blocked(None, "SOURCE_INVALID:ROOT")
        if payload.get("schema") != SCHEMA:
            return self._blocked(payload, "SOURCE_INVALID:SCHEMA")
        if payload.get("repo_sha") != expected:
            return self._blocked(payload, "SOURCE_REPO_SHA_MISMATCH")
        if not (
            payload.get("research_only") is True
            and payload.get("can_confirm_signal") is False
            and payload.get("radar_admission") == "BLOCKED"
            and payload.get("live_trade") is False
            and payload.get("intraday_timestamp_semantics_proven") is False
            and payload.get("intraday_currentness_proven") is False
        ):
            return self._blocked(payload, "SOURCE_SAFETY_CONTRACT_VIOLATION")
        if payload.get("status") != "PASS":
            return self._blocked(payload, "SOURCE_STATUS_NOT_PASS")

        emitted = _aware_timestamp(payload.get("emitted_at_utc"))
        if emitted is None:
            return self._blocked(payload, "SOURCE_EMITTED_AT_INVALID")
        now = now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now_utc must be timezone-aware")
        signed_age = (now.astimezone(timezone.utc) - emitted).total_seconds()
        if signed_age < -5:
            return self._blocked(payload, "SOURCE_FROM_FUTURE")
        if signed_age > self._max_age_seconds:
            return self._blocked(payload, "SOURCE_STALE")

        symbols = payload.get("symbols")
        if not isinstance(symbols, Mapping) or not symbols:
            return self._blocked(payload, "SOURCE_SYMBOLS_MISSING")

        results: list[dict] = []
        for raw_symbol in sorted(symbols):
            symbol = str(raw_symbol).strip().upper()
            item = symbols[raw_symbol]
            result = self._evaluate_symbol(symbol, item)
            results.append(result)

        if not results or any(item["status"] != "RESEARCH_STATE" for item in results):
            return CNCloudRadarEvaluation(
                status="PARTIAL",
                source_repo_sha=expected,
                source_runtime_instance_id=str(payload.get("runtime_instance_id") or "") or None,
                source_sequence=_int_or_none(payload.get("sequence")),
                source_emitted_at_utc=emitted.isoformat(),
                symbols=tuple(results),
                reasons=("SYMBOL_EVALUATION_BLOCKED",),
            )

        return CNCloudRadarEvaluation(
            status="PASS",
            source_repo_sha=expected,
            source_runtime_instance_id=str(payload.get("runtime_instance_id") or "") or None,
            source_sequence=_int_or_none(payload.get("sequence")),
            source_emitted_at_utc=emitted.isoformat(),
            symbols=tuple(results),
        )

    def _evaluate_symbol(self, symbol: str, item: object) -> dict:
        if len(symbol) != 6 or not symbol.isdigit() or not isinstance(item, Mapping):
            return _symbol_blocked(symbol, "SYMBOL_CONTRACT_INVALID")
        if not (
            item.get("status") == "PASS"
            and item.get("research_only") is True
            and item.get("can_confirm_signal") is False
            and item.get("radar_admission") == "BLOCKED"
            and item.get("live_trade") is False
            and item.get("intraday_timestamp_semantics_proven") is False
            and item.get("intraday_currentness_proven") is False
        ):
            return _symbol_blocked(symbol, "SYMBOL_SAFETY_CONTRACT_VIOLATION")

        frames = item.get("timeframes")
        if not isinstance(frames, Mapping):
            return _symbol_blocked(symbol, "TIMEFRAMES_MISSING")

        parsed: dict[str, pd.DataFrame] = {}
        providers: dict[str, str] = {}
        fallbacks: dict[str, str | None] = {}
        for timeframe in TIMEFRAMES:
            frame = frames.get(timeframe)
            if not isinstance(frame, Mapping):
                return _symbol_blocked(symbol, f"{timeframe}:FRAME_MISSING")
            expected_semantic = "DAILY_DATE" if timeframe == "1d" else "UNKNOWN"
            if not (
                frame.get("status") == "PASS"
                and frame.get("timestamp_semantic") == expected_semantic
                and frame.get("currentness") == "UNPROVEN"
            ):
                return _symbol_blocked(symbol, f"{timeframe}:FRAME_CONTRACT_INVALID")
            provider = str(frame.get("provider_used") or "").strip().lower()
            lineage = str(frame.get("provider_lineage") or "").strip().lower()
            if provider not in {"eastmoney", "tencent"} or lineage != provider:
                return _symbol_blocked(symbol, f"{timeframe}:PROVIDER_LINEAGE_INVALID")
            rows = frame.get("rows")
            if not isinstance(rows, list) or len(rows) < 20:
                return _symbol_blocked(symbol, f"{timeframe}:INSUFFICIENT_ROWS")
            parsed_frame, reason = _rows_frame(rows, timeframe=timeframe)
            if reason is not None:
                return _symbol_blocked(symbol, f"{timeframe}:{reason}")
            parsed[timeframe] = parsed_frame
            providers[timeframe] = provider
            fallbacks[timeframe] = (
                None if frame.get("fallback_from") is None else str(frame.get("fallback_from"))
            )

        technical = self._analyzer.analyze(
            symbol,
            parsed["1d"],
            parsed["60m"],
            parsed["15m"],
        )
        technical.daily = _mark_unproven(
            technical.daily,
            warnings=("1d_currentness_unproven", "1d_provider_units_unverified"),
            confidence_cap=0.75,
        )
        technical.hourly = _mark_unproven(
            technical.hourly,
            warnings=(
                "1h_timestamp_semantics_unverified",
                "1h_currentness_unproven",
                "1h_provider_units_unverified",
            ),
            confidence_cap=0.65,
        )
        technical.intraday = _mark_unproven(
            technical.intraday,
            warnings=(
                "15m_timestamp_semantics_unverified",
                "15m_currentness_unproven",
                "15m_provider_units_unverified",
            ),
            confidence_cap=0.65,
        )
        extra_risks = [
            *technical.daily.quality.warnings,
            *technical.hourly.quality.warnings,
            *technical.intraday.quality.warnings,
        ]
        if any(value for value in fallbacks.values()):
            extra_risks.append("provider_fallback_used")
        if len(set(providers.values())) > 1:
            extra_risks.append("mixed_provider_lineage")
        technical.risk_flags = list(dict.fromkeys([*technical.risk_flags, *extra_risks]))

        return {
            "symbol": symbol,
            "status": "RESEARCH_STATE",
            "technical": technical.to_dict(),
            "providers": providers,
            "fallbacks": fallbacks,
            "source_timeframe_rows": {
                timeframe: len(parsed[timeframe]) for timeframe in TIMEFRAMES
            },
            "research_only": True,
            "can_confirm_signal": False,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }

    @staticmethod
    def _blocked(payload: Mapping | None, reason: str) -> CNCloudRadarEvaluation:
        source = payload if isinstance(payload, Mapping) else {}
        return CNCloudRadarEvaluation(
            status="BLOCKED",
            source_repo_sha=(
                str(source.get("repo_sha") or "").strip().lower() or None
            ),
            source_runtime_instance_id=(
                str(source.get("runtime_instance_id") or "").strip() or None
            ),
            source_sequence=_int_or_none(source.get("sequence")),
            source_emitted_at_utc=(
                str(source.get("emitted_at_utc") or "").strip() or None
            ),
            reasons=(reason,),
        )


def _rows_frame(rows: list[object], *, timeframe: str) -> tuple[pd.DataFrame, str | None]:
    normalized: list[dict] = []
    previous_label: str | None = None
    for raw in rows:
        if not isinstance(raw, Mapping):
            return pd.DataFrame(), "ROW_SHAPE_INVALID"
        label = str(raw.get("label") or "").strip()
        if not label or (previous_label is not None and label <= previous_label):
            return pd.DataFrame(), "LABEL_ORDER_INVALID"
        previous_label = label
        flags = [
            str(flag).strip().upper()
            for flag in (raw.get("quality_flags") or [])
            if str(flag).strip()
        ]
        if flags:
            return pd.DataFrame(), "STRUCTURAL_QUALITY_FLAG_PRESENT"
        try:
            date = pd.Timestamp(label)
            open_ = float(raw["open"])
            high = float(raw["high"])
            low = float(raw["low"])
            close = float(raw["close"])
            volume = float(raw["volume_raw"])
        except Exception:
            return pd.DataFrame(), "ROW_NUMERIC_INVALID"
        if min(open_, high, low, close) <= 0:
            return pd.DataFrame(), "NON_POSITIVE_PRICE"
        if high < max(open_, close, low) or low > min(open_, close, high):
            return pd.DataFrame(), "INVALID_OHLC"
        if volume < 0:
            return pd.DataFrame(), "NEGATIVE_VOLUME"
        normalized.append(
            {
                "date": date,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    return pd.DataFrame(normalized), None


def _mark_unproven(
    state: TimeframeState,
    *,
    warnings: tuple[str, ...],
    confidence_cap: float,
) -> TimeframeState:
    quality = replace(
        state.quality,
        status="partial",
        warnings=list(dict.fromkeys([*state.quality.warnings, *warnings])),
    )
    return replace(
        state,
        confidence=min(state.confidence, confidence_cap),
        quality=quality,
    )


def _symbol_blocked(symbol: str, reason: str) -> dict:
    return {
        "symbol": symbol,
        "status": "BLOCKED",
        "technical": None,
        "reasons": [reason],
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def _aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _int_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

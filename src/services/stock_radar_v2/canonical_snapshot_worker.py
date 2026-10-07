from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from data_provider.market_data_adapter import (
    Bar,
    HealthGrade,
    MarketDataHealth,
    SignalPermission,
)
from src.services.live_feed.canonical_snapshot_export import SCHEMA
from src.services.realtime_market_data import ACTIVE_SESSIONS, MarketDataSnapshot
from src.services.stock_radar_v2.technical_state import (
    StockRadarTechnicalState,
    StockRadarTechnicalStateService,
)


class CanonicalSnapshotContractError(ValueError):
    """Raised when exported canonical market-data facts violate the schema contract."""


@dataclass(frozen=True)
class CanonicalSnapshotSource:
    schema: str
    repo_sha: str
    runtime_instance_id: str
    sequence: int
    emitted_at: datetime
    market_state_us: str
    cache_session_us: str
    delivery_mode: str
    bar_closure: str
    radar_admission: str
    live_trade: bool
    snapshots: tuple[MarketDataSnapshot, ...]


@dataclass(frozen=True)
class CanonicalRadarSymbolResult:
    symbol: str
    status: str
    technical_state: StockRadarTechnicalState | None = None
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "technical_state": (
                self.technical_state.to_dict()
                if self.technical_state is not None
                else None
            ),
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class CanonicalRadarEvaluation:
    status: str
    source_repo_sha: str | None
    runtime_instance_id: str | None
    source_sequence: int | None
    source_emitted_at: datetime | None
    source_delivery_mode: str | None
    source_bar_closure: str | None
    source_radar_admission: str | None
    source_live_trade: bool | None
    symbols: tuple[CanonicalRadarSymbolResult, ...] = ()
    reasons: tuple[str, ...] = ()
    research_only: bool = field(default=True, init=False)
    can_confirm_signal: bool = field(default=False, init=False)

    def admission_diagnostics(self) -> dict:
        """Expose bounded admission evidence without authorizing promotion."""

        delivery_mode_realtime = self.source_delivery_mode == "REALTIME"
        bar_closure_proven = self.source_bar_closure == "PROVEN"
        research_state_symbols = [
            item.symbol for item in self.symbols if item.status == "RESEARCH_STATE"
        ]
        no_canonical_bar_symbols = [
            item.symbol for item in self.symbols if item.status == "NO_CANONICAL_BARS"
        ]
        normal_health_symbols = [
            item.symbol
            for item in self.symbols
            if item.technical_state is not None
            and item.technical_state.signal_permission is SignalPermission.NORMAL
        ]
        non_normal_health_symbols = [
            item.symbol
            for item in self.symbols
            if item.technical_state is not None
            and item.technical_state.signal_permission is not SignalPermission.NORMAL
        ]

        reasons = list(self.reasons)
        if self.source_delivery_mode is None:
            reasons.append("SOURCE_DELIVERY_MODE_UNAVAILABLE")
        elif not delivery_mode_realtime:
            reasons.append("SOURCE_DELIVERY_MODE_NOT_REALTIME")
        if self.source_bar_closure is None:
            reasons.append("SOURCE_BAR_CLOSURE_UNAVAILABLE")
        elif not bar_closure_proven:
            reasons.append("SOURCE_BAR_CLOSURE_UNPROVEN")
        if no_canonical_bar_symbols:
            reasons.append("SYMBOLS_WITHOUT_CANONICAL_BARS")
        if non_normal_health_symbols:
            reasons.append("SYMBOL_DATA_HEALTH_NOT_NORMAL")
        reasons.append("PROMOTION_NOT_AUTHORIZED")

        return {
            "decision": "BLOCKED",
            "promotion_authorized": False,
            "minimum_source_prerequisites_met": (
                delivery_mode_realtime and bar_closure_proven
            ),
            "delivery_mode_realtime": delivery_mode_realtime,
            "bar_closure_proven": bar_closure_proven,
            "source_radar_admission": self.source_radar_admission,
            "source_live_trade": self.source_live_trade,
            "research_state_symbols": research_state_symbols,
            "no_canonical_bar_symbols": no_canonical_bar_symbols,
            "normal_health_symbols": normal_health_symbols,
            "non_normal_health_symbols": non_normal_health_symbols,
            "reasons": list(dict.fromkeys(reasons)),
        }

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "source_repo_sha": self.source_repo_sha,
            "runtime_instance_id": self.runtime_instance_id,
            "source_sequence": self.source_sequence,
            "source_emitted_at": (
                self.source_emitted_at.isoformat()
                if self.source_emitted_at is not None
                else None
            ),
            "source_delivery_mode": self.source_delivery_mode,
            "source_bar_closure": self.source_bar_closure,
            "source_radar_admission": self.source_radar_admission,
            "source_live_trade": self.source_live_trade,
            "symbols": [item.to_dict() for item in self.symbols],
            "reasons": list(self.reasons),
            "research_only": self.research_only,
            "can_confirm_signal": self.can_confirm_signal,
            "admission_diagnostics": self.admission_diagnostics(),
        }


def _parse_time(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalSnapshotContractError(f"{field_name} must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CanonicalSnapshotContractError(f"{field_name} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CanonicalSnapshotContractError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _health(payload: object, *, field_name: str, required: bool) -> MarketDataHealth | None:
    if payload is None:
        if required:
            raise CanonicalSnapshotContractError(f"{field_name} is required")
        return None
    if not isinstance(payload, Mapping):
        raise CanonicalSnapshotContractError(f"{field_name} must be an object")
    try:
        score = int(payload["score"])
        grade = HealthGrade(str(payload["grade"]))
        permission = SignalPermission(str(payload["signal_permission"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalSnapshotContractError(f"{field_name} has invalid health fields") from exc
    if not 0 <= score <= 100:
        raise CanonicalSnapshotContractError(f"{field_name}.score must be between 0 and 100")
    flags_raw = payload.get("quality_flags") or []
    if not isinstance(flags_raw, list):
        raise CanonicalSnapshotContractError(f"{field_name}.quality_flags must be a list")
    flags = tuple(str(flag).strip().upper() for flag in flags_raw if str(flag).strip())
    return MarketDataHealth(score=score, grade=grade, signal_permission=permission, quality_flags=flags)


def _finite_float(value: object, *, field_name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CanonicalSnapshotContractError(f"{field_name} must be numeric") from exc
    if not math.isfinite(parsed):
        raise CanonicalSnapshotContractError(f"{field_name} must be finite")
    return parsed


def _optional_float(payload: Mapping, key: str, *, field_name: str) -> float | None:
    value = payload.get(key)
    return None if value is None else _finite_float(value, field_name=f"{field_name}.{key}")


def _required_bool(payload: Mapping, key: str, *, field_name: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise CanonicalSnapshotContractError(f"{field_name}.{key} must be boolean")
    return value


def _bar(payload: object, *, symbol: str, timeframe: str, index: int) -> Bar:
    field_name = f"symbols.{symbol}.timeframes.{timeframe}[{index}]"
    if not isinstance(payload, Mapping):
        raise CanonicalSnapshotContractError(f"{field_name} must be an object")
    actual_symbol = str(payload.get("symbol") or "").strip().upper()
    if actual_symbol != symbol:
        raise CanonicalSnapshotContractError(f"{field_name}.symbol mismatch")
    actual_timeframe = str(payload.get("timeframe") or "").strip()
    if actual_timeframe != timeframe:
        raise CanonicalSnapshotContractError(f"{field_name}.timeframe mismatch")
    start = _parse_time(payload.get("bar_start_utc"), field_name=f"{field_name}.bar_start_utc")
    end = _parse_time(payload.get("bar_end_utc"), field_name=f"{field_name}.bar_end_utc")
    if end <= start:
        raise CanonicalSnapshotContractError(f"{field_name} must have bar_end after bar_start")
    source_timestamp = _parse_time(
        payload.get("source_timestamp_utc"),
        field_name=f"{field_name}.source_timestamp_utc",
    )
    received_at = _parse_time(
        payload.get("received_at_utc"),
        field_name=f"{field_name}.received_at_utc",
    )
    try:
        open_ = _finite_float(payload["open"], field_name=f"{field_name}.open")
        high = _finite_float(payload["high"], field_name=f"{field_name}.high")
        low = _finite_float(payload["low"], field_name=f"{field_name}.low")
        close = _finite_float(payload["close"], field_name=f"{field_name}.close")
        volume = _finite_float(payload["volume"], field_name=f"{field_name}.volume")
    except KeyError as exc:
        raise CanonicalSnapshotContractError(f"{field_name} has missing OHLCV") from exc
    if volume < 0:
        raise CanonicalSnapshotContractError(f"{field_name}.volume must be non-negative")
    if high < max(open_, close, low) or low > min(open_, close, high):
        raise CanonicalSnapshotContractError(f"{field_name} has invalid OHLC")
    flags_raw = payload.get("quality_flags") or []
    if not isinstance(flags_raw, list):
        raise CanonicalSnapshotContractError(f"{field_name}.quality_flags must be a list")
    health = _health(payload.get("health"), field_name=f"{field_name}.health", required=False)
    return Bar(
        symbol=symbol,
        market=str(payload.get("market") or ""),
        asset_type=str(payload.get("asset_type") or ""),
        timeframe=timeframe,
        bar_start=start,
        bar_end=end,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        amount=_optional_float(payload, "amount", field_name=field_name),
        vwap=_optional_float(payload, "vwap", field_name=field_name),
        provider=str(payload.get("provider") or ""),
        feed=None if payload.get("feed") is None else str(payload.get("feed")),
        source_timestamp=source_timestamp,
        received_at=received_at,
        session=str(payload.get("session") or ""),
        is_closed=_required_bool(payload, "is_closed", field_name=field_name),
        is_complete=_required_bool(payload, "is_complete", field_name=field_name),
        fallback_from=None if payload.get("fallback_from") is None else str(payload.get("fallback_from")),
        fallback_reason=None if payload.get("fallback_reason") is None else str(payload.get("fallback_reason")),
        latency_ms=int(payload.get("latency_ms") or 0),
        freshness_ms=int(payload.get("freshness_ms") or 0),
        health=health,
        quality_flags=tuple(str(flag).strip().upper() for flag in flags_raw if str(flag).strip()),
    )


def _bars(payload: object, *, symbol: str, timeframe: str) -> tuple[Bar, ...]:
    if not isinstance(payload, list):
        raise CanonicalSnapshotContractError(
            f"symbols.{symbol}.timeframes.{timeframe} must be a list"
        )
    bars = tuple(_bar(item, symbol=symbol, timeframe=timeframe, index=index) for index, item in enumerate(payload))
    starts = [bar.bar_start for bar in bars]
    if starts != sorted(starts) or len(set(starts)) != len(starts):
        raise CanonicalSnapshotContractError(
            f"symbols.{symbol}.timeframes.{timeframe} must be strictly ordered and unique"
        )
    return bars


def load_canonical_snapshot_payload(payload: object) -> CanonicalSnapshotSource:
    if not isinstance(payload, Mapping):
        raise CanonicalSnapshotContractError("canonical snapshot root must be an object")
    if payload.get("schema") != SCHEMA:
        raise CanonicalSnapshotContractError("unsupported canonical snapshot schema")
    repo_sha = str(payload.get("repo_sha") or "").strip().lower()
    if len(repo_sha) != 40 or any(ch not in "0123456789abcdef" for ch in repo_sha):
        raise CanonicalSnapshotContractError("repo_sha must be an exact 40-character git SHA")
    runtime_instance_id = str(payload.get("runtime_instance_id") or "").strip()
    if not runtime_instance_id:
        raise CanonicalSnapshotContractError("runtime_instance_id is required")
    try:
        sequence = int(payload["sequence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonicalSnapshotContractError("sequence must be an integer") from exc
    if sequence <= 0:
        raise CanonicalSnapshotContractError("sequence must be positive")
    emitted_at = _parse_time(payload.get("emitted_at_utc"), field_name="emitted_at_utc")
    delivery_mode = str(payload.get("delivery_mode") or "UNKNOWN").strip().upper()
    if delivery_mode not in {"UNKNOWN", "REALTIME"}:
        raise CanonicalSnapshotContractError(
            "source delivery_mode must be UNKNOWN or REALTIME"
        )
    bar_closure = str(payload.get("bar_closure") or "UNPROVEN").strip().upper()
    if bar_closure not in {"UNPROVEN", "PROVEN"}:
        raise CanonicalSnapshotContractError("source bar_closure must be UNPROVEN or PROVEN")
    radar_admission = str(payload.get("radar_admission") or "BLOCKED").strip().upper()
    if radar_admission != "BLOCKED":
        raise CanonicalSnapshotContractError("source radar_admission must remain BLOCKED")
    if payload.get("live_trade") is not False:
        raise CanonicalSnapshotContractError("source live_trade must remain false")

    symbols_raw = payload.get("symbols")
    if not isinstance(symbols_raw, Mapping):
        raise CanonicalSnapshotContractError("symbols must be an object")
    if not symbols_raw:
        raise CanonicalSnapshotContractError("symbols must not be empty")
    snapshots: list[MarketDataSnapshot] = []
    for raw_symbol in sorted(symbols_raw):
        symbol = str(raw_symbol).strip().upper()
        item = symbols_raw[raw_symbol]
        if not isinstance(item, Mapping):
            raise CanonicalSnapshotContractError(f"symbols.{symbol} must be an object")
        if str(item.get("symbol") or "").strip().upper() != symbol:
            raise CanonicalSnapshotContractError(f"symbols.{symbol}.symbol mismatch")
        frames = item.get("timeframes")
        if not isinstance(frames, Mapping):
            raise CanonicalSnapshotContractError(f"symbols.{symbol}.timeframes must be an object")
        minute_bars = _bars(frames.get("1m"), symbol=symbol, timeframe="1m")
        bars_5m = _bars(frames.get("5m"), symbol=symbol, timeframe="5m")
        bars_15m = _bars(frames.get("15m"), symbol=symbol, timeframe="15m")
        bars_1h = _bars(frames.get("1h"), symbol=symbol, timeframe="1h")
        snapshots.append(
            MarketDataSnapshot(
                symbol=symbol,
                as_of=_parse_time(item.get("as_of_utc"), field_name=f"symbols.{symbol}.as_of_utc"),
                minute_bars=minute_bars,
                bars_5m=bars_5m,
                bars_15m=bars_15m,
                bars_1h=bars_1h,
                health=_health(item.get("health"), field_name=f"symbols.{symbol}.health", required=True),
                provider=None if item.get("provider") is None else str(item.get("provider")),
                feed=None if item.get("feed") is None else str(item.get("feed")),
                fallback_from=None if item.get("fallback_from") is None else str(item.get("fallback_from")),
                fallback_reason=None if item.get("fallback_reason") is None else str(item.get("fallback_reason")),
                owner_identity=None if item.get("owner_identity") is None else str(item.get("owner_identity")),
                runtime_generation=None if item.get("runtime_generation") is None else int(item.get("runtime_generation")),
            )
        )

    return CanonicalSnapshotSource(
        schema=SCHEMA,
        repo_sha=repo_sha,
        runtime_instance_id=runtime_instance_id,
        sequence=sequence,
        emitted_at=emitted_at,
        market_state_us=str(payload.get("market_state_us") or "UNKNOWN"),
        cache_session_us=str(payload.get("cache_session_us") or "unknown").strip().lower(),
        delivery_mode=delivery_mode,
        bar_closure=bar_closure,
        radar_admission=radar_admission,
        live_trade=False,
        snapshots=tuple(snapshots),
    )


def load_canonical_snapshot_file(path: str | Path) -> CanonicalSnapshotSource:
    with Path(path).open(encoding="utf-8") as handle:
        return load_canonical_snapshot_payload(json.load(handle))


class CanonicalSnapshotRadarEvaluator:
    """Evaluate exported canonical snapshots without opening a provider path."""

    def __init__(
        self,
        technical_state_service: StockRadarTechnicalStateService | None = None,
        *,
        max_active_age_seconds: int = 120,
        max_future_skew_seconds: int = 5,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if max_active_age_seconds <= 0:
            raise ValueError("max_active_age_seconds must be positive")
        if max_future_skew_seconds < 0:
            raise ValueError("max_future_skew_seconds must be non-negative")
        self._technical = technical_state_service or StockRadarTechnicalStateService()
        self._max_active_age_seconds = max_active_age_seconds
        self._max_future_skew_seconds = max_future_skew_seconds
        self._now = now

    def evaluate_file(
        self,
        path: str | Path,
        *,
        expected_repo_sha: str | None = None,
    ) -> CanonicalRadarEvaluation:
        try:
            source = load_canonical_snapshot_file(path)
        except (OSError, json.JSONDecodeError, CanonicalSnapshotContractError) as exc:
            return CanonicalRadarEvaluation(
                status="BLOCKED",
                source_repo_sha=None,
                runtime_instance_id=None,
                source_sequence=None,
                source_emitted_at=None,
                source_delivery_mode=None,
                source_bar_closure=None,
                source_radar_admission=None,
                source_live_trade=None,
                reasons=(f"SOURCE_INVALID:{type(exc).__name__}",),
            )
        return self.evaluate_source(source, expected_repo_sha=expected_repo_sha)

    def preflight_source(
        self,
        source: CanonicalSnapshotSource,
        *,
        expected_repo_sha: str | None = None,
    ) -> CanonicalRadarEvaluation | None:
        if expected_repo_sha is not None and source.repo_sha != expected_repo_sha.lower():
            return self._blocked(source, "SOURCE_REPO_SHA_MISMATCH")
        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        now_utc = now.astimezone(timezone.utc)
        signed_age_seconds = (now_utc - source.emitted_at).total_seconds()
        if signed_age_seconds < -self._max_future_skew_seconds:
            return self._blocked(source, "SOURCE_EXPORT_FROM_FUTURE")
        if source.cache_session_us in ACTIVE_SESSIONS:
            age_seconds = max(0.0, signed_age_seconds)
            if age_seconds > self._max_active_age_seconds:
                return self._blocked(source, "SOURCE_EXPORT_STALE")
        return None

    def evaluate_source(
        self,
        source: CanonicalSnapshotSource,
        *,
        expected_repo_sha: str | None = None,
    ) -> CanonicalRadarEvaluation:
        blocked = self.preflight_source(
            source,
            expected_repo_sha=expected_repo_sha,
        )
        if blocked is not None:
            return blocked

        results: list[CanonicalRadarSymbolResult] = []
        for snapshot in source.snapshots:
            if not snapshot.minute_bars:
                results.append(
                    CanonicalRadarSymbolResult(
                        symbol=snapshot.symbol,
                        status="NO_CANONICAL_BARS",
                        reasons=("NO_CANONICAL_BARS",),
                    )
                )
                continue
            state = self._technical.evaluate(snapshot)
            results.append(
                CanonicalRadarSymbolResult(
                    symbol=snapshot.symbol,
                    status="RESEARCH_STATE",
                    technical_state=state,
                )
            )
        return CanonicalRadarEvaluation(
            status="PASS",
            source_repo_sha=source.repo_sha,
            runtime_instance_id=source.runtime_instance_id,
            source_sequence=source.sequence,
            source_emitted_at=source.emitted_at,
            source_delivery_mode=source.delivery_mode,
            source_bar_closure=source.bar_closure,
            source_radar_admission=source.radar_admission,
            source_live_trade=source.live_trade,
            symbols=tuple(results),
        )

    @staticmethod
    def _blocked(source: CanonicalSnapshotSource, reason: str) -> CanonicalRadarEvaluation:
        return CanonicalRadarEvaluation(
            status="BLOCKED",
            source_repo_sha=source.repo_sha,
            runtime_instance_id=source.runtime_instance_id,
            source_sequence=source.sequence,
            source_emitted_at=source.emitted_at,
            source_delivery_mode=source.delivery_mode,
            source_bar_closure=source.bar_closure,
            source_radar_admission=source.radar_admission,
            source_live_trade=source.live_trade,
            reasons=(reason,),
        )


class CanonicalSnapshotRadarWorker:
    """Stateful poller that enforces runtime-local export sequence monotonicity."""

    def __init__(
        self,
        *,
        expected_repo_sha: str,
        evaluator: CanonicalSnapshotRadarEvaluator | None = None,
    ) -> None:
        normalized_sha = str(expected_repo_sha).strip().lower()
        if len(normalized_sha) != 40 or any(ch not in "0123456789abcdef" for ch in normalized_sha):
            raise ValueError("expected_repo_sha must be an exact 40-character git SHA")
        self._expected_repo_sha = normalized_sha
        self._evaluator = evaluator or CanonicalSnapshotRadarEvaluator()
        self._last_runtime_instance_id: str | None = None
        self._last_sequence: int | None = None
        self._last_successful_evaluation: CanonicalRadarEvaluation | None = None

    def poll_file(self, path: str | Path) -> CanonicalRadarEvaluation:
        try:
            source = load_canonical_snapshot_file(path)
        except (OSError, json.JSONDecodeError, CanonicalSnapshotContractError):
            return self._evaluator.evaluate_file(
                path,
                expected_repo_sha=self._expected_repo_sha,
            )

        blocked = self._evaluator.preflight_source(
            source,
            expected_repo_sha=self._expected_repo_sha,
        )
        if blocked is not None:
            return blocked

        if self._last_runtime_instance_id == source.runtime_instance_id and self._last_sequence is not None:
            if source.sequence < self._last_sequence:
                return self._blocked(source, "SOURCE_SEQUENCE_REGRESSION")
            if source.sequence == self._last_sequence:
                return CanonicalRadarEvaluation(
                    status="UNCHANGED",
                    source_repo_sha=source.repo_sha,
                    runtime_instance_id=source.runtime_instance_id,
                    source_sequence=source.sequence,
                    source_emitted_at=source.emitted_at,
                    source_delivery_mode=source.delivery_mode,
                    source_bar_closure=source.bar_closure,
                    source_radar_admission=source.radar_admission,
                    source_live_trade=source.live_trade,
                    symbols=(
                        self._last_successful_evaluation.symbols
                        if self._last_successful_evaluation is not None
                        else ()
                    ),
                    reasons=("SOURCE_SEQUENCE_UNCHANGED",),
                )

        evaluation = self._evaluator.evaluate_source(
            source,
            expected_repo_sha=self._expected_repo_sha,
        )
        if evaluation.status == "PASS":
            self._last_runtime_instance_id = source.runtime_instance_id
            self._last_sequence = source.sequence
            self._last_successful_evaluation = evaluation
        return evaluation

    @staticmethod
    def _blocked(source: CanonicalSnapshotSource, reason: str) -> CanonicalRadarEvaluation:
        return CanonicalRadarEvaluation(
            status="BLOCKED",
            source_repo_sha=source.repo_sha,
            runtime_instance_id=source.runtime_instance_id,
            source_sequence=source.sequence,
            source_emitted_at=source.emitted_at,
            source_delivery_mode=source.delivery_mode,
            source_bar_closure=source.bar_closure,
            source_radar_admission=source.radar_admission,
            source_live_trade=source.live_trade,
            reasons=(reason,),
        )

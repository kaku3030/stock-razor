"""Fail-closed reader for US options-intelligence sidecar snapshots."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from src.services.options_intelligence.runtime_snapshot import SCHEMA


class OptionsContextContractError(ValueError):
    """Raised when the options sidecar violates the research contract."""


def _parse_time(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise OptionsContextContractError(f"{field_name} must be a non-empty ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise OptionsContextContractError(f"{field_name} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OptionsContextContractError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _exact_sha(value: object) -> str:
    sha = str(value or "").strip().lower()
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        raise OptionsContextContractError("repo_sha must be an exact 40-character git SHA")
    return sha


def _finite_optional(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise OptionsContextContractError(f"{field_name} must be numeric or null") from exc
    if not math.isfinite(number):
        raise OptionsContextContractError(f"{field_name} must be finite")
    return number


@dataclass(frozen=True)
class RadarOptionsContext:
    symbol: str
    generated_at: datetime
    context_permission: str
    radar_admission: str
    decision_permission: str
    options_regime: str | None
    net_gex: float | None
    gamma_flip: float | None
    gamma_flip_status: str | None
    call_wall: float | None
    put_wall: float | None
    zero_dte_share: float | None
    completeness: float | None
    clock_status: str
    unknown_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    research_only: bool = True
    trading_authority: bool = False
    live_trade: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "generated_at": self.generated_at.isoformat(),
            "context_permission": self.context_permission,
            "radar_admission": self.radar_admission,
            "decision_permission": self.decision_permission,
            "options_regime": self.options_regime,
            "net_gex": self.net_gex,
            "gamma_flip": self.gamma_flip,
            "gamma_flip_status": self.gamma_flip_status,
            "call_wall": self.call_wall,
            "put_wall": self.put_wall,
            "zero_dte_share": self.zero_dte_share,
            "completeness": self.completeness,
            "clock_status": self.clock_status,
            "unknown_fields": list(self.unknown_fields),
            "warnings": list(self.warnings),
            "research_only": self.research_only,
            "trading_authority": self.trading_authority,
            "live_trade": self.live_trade,
        }


@dataclass(frozen=True)
class OptionsContextSnapshotSource:
    repo_sha: str
    runtime_instance_id: str
    sequence: int
    emitted_at: datetime
    contexts: tuple[RadarOptionsContext, ...]


@dataclass(frozen=True)
class OptionsContextReadResult:
    status: str
    source_repo_sha: str | None
    runtime_instance_id: str | None
    source_sequence: int | None
    source_emitted_at: datetime | None
    contexts: tuple[RadarOptionsContext, ...] = ()
    reasons: tuple[str, ...] = ()
    research_only: bool = True
    trading_authority: bool = False
    live_trade: bool = False

    def by_symbol(self) -> dict[str, RadarOptionsContext]:
        return {item.symbol: item for item in self.contexts}

    def to_dict(self) -> dict[str, object]:
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
            "contexts": [item.to_dict() for item in self.contexts],
            "reasons": list(self.reasons),
            "research_only": self.research_only,
            "trading_authority": self.trading_authority,
            "live_trade": self.live_trade,
        }


def _canonical_symbol(value: object) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise OptionsContextContractError("symbol is required")
    return symbol if symbol.startswith("US.") else f"US.{symbol}"


def _parse_context(symbol: str, payload: object) -> RadarOptionsContext:
    if not isinstance(payload, Mapping):
        raise OptionsContextContractError(f"symbols.{symbol} must be an object")
    underlying = _canonical_symbol(payload.get("underlying_symbol"))
    if underlying != symbol:
        raise OptionsContextContractError(f"symbols.{symbol}.underlying_symbol mismatch")

    if payload.get("trading_authority") is not False:
        raise OptionsContextContractError(f"symbols.{symbol}.trading_authority must be false")
    if payload.get("live_trade") is not False:
        raise OptionsContextContractError(f"symbols.{symbol}.live_trade must be false")
    if payload.get("decision_permission") != "BLOCKED_V0_1":
        raise OptionsContextContractError(f"symbols.{symbol}.decision_permission must remain blocked")
    if payload.get("price_acceptance_required") is not True:
        raise OptionsContextContractError(f"symbols.{symbol}.price_acceptance_required must be true")

    context_permission = str(payload.get("context_permission") or "").strip().upper()
    if context_permission not in {"BLOCKED", "DEGRADED_RESEARCH", "RESEARCH_ONLY"}:
        raise OptionsContextContractError(f"symbols.{symbol}.context_permission is invalid")
    radar_admission = str(payload.get("radar_admission") or "").strip().upper()
    if radar_admission not in {"BLOCKED", "CONTEXT_ONLY"}:
        raise OptionsContextContractError(f"symbols.{symbol}.radar_admission is invalid")
    if context_permission == "BLOCKED" and radar_admission != "BLOCKED":
        raise OptionsContextContractError(
            f"symbols.{symbol} cannot admit blocked context"
        )

    generated_at = _parse_time(
        payload.get("generated_at"),
        field_name=f"symbols.{symbol}.generated_at",
    )
    current = payload.get("current_gex")
    if not isinstance(current, Mapping):
        raise OptionsContextContractError(f"symbols.{symbol}.current_gex must be an object")
    if current.get("trading_authority") is not False:
        raise OptionsContextContractError(
            f"symbols.{symbol}.current_gex.trading_authority must be false"
        )
    if current.get("research_only") is not True:
        raise OptionsContextContractError(
            f"symbols.{symbol}.current_gex.research_only must be true"
        )

    expiry = current.get("expiry_concentration")
    if expiry is not None and not isinstance(expiry, Mapping):
        raise OptionsContextContractError(
            f"symbols.{symbol}.current_gex.expiry_concentration must be an object"
        )

    clock = payload.get("clock_alignment")
    if not isinstance(clock, Mapping):
        raise OptionsContextContractError(
            f"symbols.{symbol}.clock_alignment is required"
        )
    clock_status = str(clock.get("status") or "").strip().upper()
    if clock_status not in {"BLOCKED", "DEGRADED", "PASS_RESEARCH"}:
        raise OptionsContextContractError(
            f"symbols.{symbol}.clock_alignment.status is invalid"
        )
    if clock_status == "BLOCKED" and context_permission != "BLOCKED":
        raise OptionsContextContractError(
            f"symbols.{symbol} cannot expose context when clock alignment is blocked"
        )

    unknown_raw = payload.get("unknown_fields") or []
    if not isinstance(unknown_raw, list):
        raise OptionsContextContractError(f"symbols.{symbol}.unknown_fields must be a list")
    warnings_raw = current.get("warnings") or []
    if not isinstance(warnings_raw, list):
        raise OptionsContextContractError(
            f"symbols.{symbol}.current_gex.warnings must be a list"
        )
    clock_warnings_raw = clock.get("warnings") or []
    if not isinstance(clock_warnings_raw, list):
        raise OptionsContextContractError(
            f"symbols.{symbol}.clock_alignment.warnings must be a list"
        )
    combined_warnings = tuple(
        dict.fromkeys(str(item) for item in [*warnings_raw, *clock_warnings_raw])
    )

    completeness = _finite_optional(
        current.get("completeness"),
        field_name=f"symbols.{symbol}.current_gex.completeness",
    )
    if completeness is not None and not 0.0 <= completeness <= 1.0:
        raise OptionsContextContractError(
            f"symbols.{symbol}.current_gex.completeness must be between 0 and 1"
        )

    zero_dte_share = None
    if isinstance(expiry, Mapping):
        zero_dte_share = _finite_optional(
            expiry.get("zero_dte_share"),
            field_name=f"symbols.{symbol}.current_gex.expiry_concentration.zero_dte_share",
        )
        if zero_dte_share is not None and not 0.0 <= zero_dte_share <= 1.0:
            raise OptionsContextContractError(
                f"symbols.{symbol}.zero_dte_share must be between 0 and 1"
            )

    return RadarOptionsContext(
        symbol=symbol,
        generated_at=generated_at,
        context_permission=context_permission,
        radar_admission=radar_admission,
        decision_permission="BLOCKED_V0_1",
        options_regime=(
            None
            if current.get("options_regime") is None
            else str(current.get("options_regime"))
        ),
        net_gex=_finite_optional(
            current.get("net_gex"),
            field_name=f"symbols.{symbol}.current_gex.net_gex",
        ),
        gamma_flip=_finite_optional(
            current.get("gamma_flip"),
            field_name=f"symbols.{symbol}.current_gex.gamma_flip",
        ),
        gamma_flip_status=(
            None
            if current.get("gamma_flip_status") is None
            else str(current.get("gamma_flip_status"))
        ),
        call_wall=_finite_optional(
            current.get("call_wall"),
            field_name=f"symbols.{symbol}.current_gex.call_wall",
        ),
        put_wall=_finite_optional(
            current.get("put_wall"),
            field_name=f"symbols.{symbol}.current_gex.put_wall",
        ),
        zero_dte_share=zero_dte_share,
        completeness=completeness,
        clock_status=clock_status,
        unknown_fields=tuple(str(item) for item in unknown_raw),
        warnings=combined_warnings,
    )


def load_options_context_snapshot_payload(
    payload: object,
) -> OptionsContextSnapshotSource:
    if not isinstance(payload, Mapping):
        raise OptionsContextContractError("options snapshot root must be an object")
    if payload.get("schema") != SCHEMA:
        raise OptionsContextContractError("unsupported options snapshot schema")
    if payload.get("research_only") is not True:
        raise OptionsContextContractError("research_only must remain true")
    if payload.get("trading_authority") is not False:
        raise OptionsContextContractError("trading_authority must remain false")
    if payload.get("live_trade") is not False:
        raise OptionsContextContractError("live_trade must remain false")

    repo_sha = _exact_sha(payload.get("repo_sha"))
    runtime_instance_id = str(payload.get("runtime_instance_id") or "").strip()
    if not runtime_instance_id:
        raise OptionsContextContractError("runtime_instance_id is required")
    try:
        sequence = int(payload["sequence"])
    except (KeyError, TypeError, ValueError) as exc:
        raise OptionsContextContractError("sequence must be an integer") from exc
    if sequence <= 0:
        raise OptionsContextContractError("sequence must be positive")
    emitted_at = _parse_time(payload.get("emitted_at_utc"), field_name="emitted_at_utc")

    symbols = payload.get("symbols")
    if not isinstance(symbols, Mapping):
        raise OptionsContextContractError("symbols must be an object")
    if not symbols:
        raise OptionsContextContractError("symbols must not be empty")

    contexts: list[RadarOptionsContext] = []
    for raw_symbol in sorted(symbols):
        symbol = _canonical_symbol(raw_symbol)
        if symbol != str(raw_symbol).strip().upper():
            raise OptionsContextContractError("snapshot symbol keys must be canonical US symbols")
        contexts.append(_parse_context(symbol, symbols[raw_symbol]))

    return OptionsContextSnapshotSource(
        repo_sha=repo_sha,
        runtime_instance_id=runtime_instance_id,
        sequence=sequence,
        emitted_at=emitted_at,
        contexts=tuple(contexts),
    )


def load_options_context_snapshot_file(
    path: str | Path,
) -> OptionsContextSnapshotSource:
    with Path(path).open(encoding="utf-8") as handle:
        return load_options_context_snapshot_payload(json.load(handle))


class RadarOptionsContextReader:
    """Read a sidecar snapshot without granting it decision authority."""

    def __init__(
        self,
        *,
        max_age_seconds: int = 120,
        max_future_skew_seconds: int = 5,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        if max_future_skew_seconds < 0:
            raise ValueError("max_future_skew_seconds must be non-negative")
        self._max_age_seconds = max_age_seconds
        self._max_future_skew_seconds = max_future_skew_seconds
        self._now = now

    def read_file(
        self,
        path: str | Path,
        *,
        expected_repo_sha: str | None = None,
    ) -> OptionsContextReadResult:
        try:
            source = load_options_context_snapshot_file(path)
        except (OSError, json.JSONDecodeError, OptionsContextContractError) as exc:
            return OptionsContextReadResult(
                status="BLOCKED",
                source_repo_sha=None,
                runtime_instance_id=None,
                source_sequence=None,
                source_emitted_at=None,
                reasons=(f"SOURCE_INVALID:{type(exc).__name__}",),
            )

        if expected_repo_sha is not None:
            try:
                expected = _exact_sha(expected_repo_sha)
            except OptionsContextContractError:
                return OptionsContextReadResult(
                    status="BLOCKED",
                    source_repo_sha=source.repo_sha,
                    runtime_instance_id=source.runtime_instance_id,
                    source_sequence=source.sequence,
                    source_emitted_at=source.emitted_at,
                    reasons=("EXPECTED_SOURCE_REPO_SHA_INVALID",),
                )
            if source.repo_sha != expected:
                return OptionsContextReadResult(
                    status="BLOCKED",
                    source_repo_sha=source.repo_sha,
                    runtime_instance_id=source.runtime_instance_id,
                    source_sequence=source.sequence,
                    source_emitted_at=source.emitted_at,
                    reasons=("SOURCE_REPO_SHA_MISMATCH",),
                )

        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        signed_age = (now.astimezone(timezone.utc) - source.emitted_at).total_seconds()
        if signed_age < -self._max_future_skew_seconds:
            return OptionsContextReadResult(
                status="BLOCKED",
                source_repo_sha=source.repo_sha,
                runtime_instance_id=source.runtime_instance_id,
                source_sequence=source.sequence,
                source_emitted_at=source.emitted_at,
                reasons=("SOURCE_EXPORT_FROM_FUTURE",),
            )
        if max(0.0, signed_age) > self._max_age_seconds:
            return OptionsContextReadResult(
                status="BLOCKED",
                source_repo_sha=source.repo_sha,
                runtime_instance_id=source.runtime_instance_id,
                source_sequence=source.sequence,
                source_emitted_at=source.emitted_at,
                reasons=("SOURCE_EXPORT_STALE",),
            )

        return OptionsContextReadResult(
            status="PASS",
            source_repo_sha=source.repo_sha,
            runtime_instance_id=source.runtime_instance_id,
            source_sequence=source.sequence,
            source_emitted_at=source.emitted_at,
            contexts=source.contexts,
        )

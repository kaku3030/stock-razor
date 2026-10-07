"""One-cycle orchestration for the network-capable options collector."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Protocol

from .collector import (
    CollectorSymbolResult,
    build_futu_options_intelligence_packet,
    resolve_us_options_session_context,
)
from .futu_opend_source import FutuOptionsFetch
from .runtime_snapshot import (
    build_options_intelligence_runtime_snapshot,
    write_options_intelligence_runtime_snapshot,
)


class OptionsSourceLike(Protocol):
    def fetch(self, symbol: str, *, evaluated_at: datetime) -> FutuOptionsFetch: ...


@dataclass(frozen=True)
class CollectorCycleResult:
    status: str
    evaluated_at: datetime
    sequence: int
    phase: str
    symbol_results: tuple[CollectorSymbolResult, ...]
    snapshot_written: bool
    output_path: str
    reasons: tuple[str, ...] = ()

    @property
    def packets_written(self) -> int:
        return sum(1 for result in self.symbol_results if result.packet is not None)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "evaluated_at": self.evaluated_at.isoformat(),
            "sequence": self.sequence,
            "phase": self.phase,
            "snapshot_written": self.snapshot_written,
            "output_path": self.output_path,
            "packets_written": self.packets_written,
            "symbols": [
                {
                    "symbol": item.symbol,
                    "status": item.status,
                    "phase": item.phase,
                    "source_contracts_total": item.source_contracts_total,
                    "normalized_contracts": item.normalized_contracts,
                    "fresh_contracts": item.fresh_contracts,
                    "radar_admission": (
                        item.packet.radar_admission if item.packet is not None else "BLOCKED"
                    ),
                    "decision_permission": (
                        item.packet.decision_permission
                        if item.packet is not None
                        else "BLOCKED"
                    ),
                    "reasons": list(item.reasons),
                }
                for item in self.symbol_results
            ],
            "reasons": list(self.reasons),
            "research_only": True,
            "trading_authority": False,
            "live_trade": False,
        }


def _safe_exception_code(exc: Exception) -> str:
    """Return a bounded, non-sensitive diagnostic code."""

    kind = type(exc).__name__
    if isinstance(exc, KeyError):
        key = str(exc.args[0]) if exc.args else "UNKNOWN_KEY"
        safe = "".join(ch for ch in key if ch.isalnum() or ch in "._-")[:80]
        return f"{kind}:{safe or 'UNKNOWN_KEY'}"
    return kind


def _canonical_symbols(symbols: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if not symbol:
            continue
        canonical = symbol if symbol.startswith("US.") else f"US.{symbol}"
        if canonical not in normalized:
            normalized.append(canonical)
    if not normalized:
        raise ValueError("at least one symbol is required")
    return tuple(normalized)


def run_options_collection_cycle(
    source: OptionsSourceLike,
    symbols: Iterable[str],
    *,
    evaluated_at: datetime,
    runtime_instance_id: str,
    repo_sha: str,
    sequence: int,
    output_path: str | Path,
) -> CollectorCycleResult:
    """Fetch, qualify and atomically publish one research-only options cycle."""

    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must be timezone-aware")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        raise ValueError("sequence must be a positive integer")

    normalized_symbols = _canonical_symbols(symbols)
    session = resolve_us_options_session_context(evaluated_at)
    destination = str(Path(output_path))

    if session.status != "READY":
        return CollectorCycleResult(
            status="BLOCKED",
            evaluated_at=evaluated_at,
            sequence=sequence,
            phase=session.phase,
            symbol_results=(),
            snapshot_written=False,
            output_path=destination,
            reasons=session.warnings or (session.status,),
        )

    results: list[CollectorSymbolResult] = []
    packets = {}
    cycle_reasons: list[str] = []

    for symbol in normalized_symbols:
        try:
            fetched = source.fetch(symbol, evaluated_at=evaluated_at)
        except Exception as exc:
            result = CollectorSymbolResult(
                symbol=symbol,
                status="BLOCKED",
                phase=session.phase,
                packet=None,
                policy=None,
                clock=None,
                source_contracts_total=0,
                normalized_contracts=0,
                fresh_contracts=0,
                reasons=(f"SOURCE_FETCH_ERROR:{_safe_exception_code(exc)}",),
            )
        else:
            try:
                result = build_futu_options_intelligence_packet(
                    symbol=fetched.symbol,
                    underlying_row=fetched.underlying_row,
                    option_rows=fetched.option_rows,
                    evaluated_at=evaluated_at,
                )
            except Exception as exc:
                result = CollectorSymbolResult(
                    symbol=symbol,
                    status="BLOCKED",
                    phase=session.phase,
                    packet=None,
                    policy=None,
                    clock=None,
                    source_contracts_total=fetched.chain_contracts,
                    normalized_contracts=0,
                    fresh_contracts=0,
                    reasons=(
                        f"QUALIFICATION_ERROR:{_safe_exception_code(exc)}",
                    ),
                )
        results.append(result)
        if result.packet is not None:
            packets[result.symbol] = result.packet
        else:
            cycle_reasons.extend(result.reasons)

    if not packets:
        return CollectorCycleResult(
            status="BLOCKED",
            evaluated_at=evaluated_at,
            sequence=sequence,
            phase=session.phase,
            symbol_results=tuple(results),
            snapshot_written=False,
            output_path=destination,
            reasons=tuple(dict.fromkeys(cycle_reasons or ["NO_QUALIFIED_PACKETS"])),
        )

    payload = build_options_intelligence_runtime_snapshot(
        packets,
        runtime_instance_id=runtime_instance_id,
        repo_sha=repo_sha,
        sequence=sequence,
        emitted_at_utc=evaluated_at,
    )
    write_options_intelligence_runtime_snapshot(output_path, payload)

    all_research = all(
        item.packet is not None and item.packet.context_permission == "RESEARCH_ONLY"
        for item in results
    )
    all_written = len(packets) == len(results)
    status = "PASS_RESEARCH" if all_research and all_written else "DEGRADED_RESEARCH"

    return CollectorCycleResult(
        status=status,
        evaluated_at=evaluated_at,
        sequence=sequence,
        phase=session.phase,
        symbol_results=tuple(results),
        snapshot_written=True,
        output_path=destination,
        reasons=tuple(dict.fromkeys(cycle_reasons)),
    )

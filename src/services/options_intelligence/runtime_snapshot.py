"""Atomic runtime export for research-only US options intelligence."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .contract import OptionsIntelligencePacket


SCHEMA = "stock_razor_us_options_intelligence_snapshot_v1"


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("runtime snapshot datetimes must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def _exact_sha(value: object) -> str:
    sha = str(value or "").strip().lower()
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ValueError("repo_sha must be an exact 40-character git SHA")
    return sha


def _canonical_us_symbol(value: str) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise ValueError("symbol is required")
    return symbol if symbol.startswith("US.") else f"US.{symbol}"


def build_options_intelligence_runtime_snapshot(
    packets: Mapping[str, OptionsIntelligencePacket],
    *,
    runtime_instance_id: str,
    repo_sha: str,
    sequence: int,
    emitted_at_utc: datetime,
) -> dict[str, object]:
    """Build a fail-closed sidecar snapshot for the isolated US Radar worker."""

    runtime = str(runtime_instance_id or "").strip()
    if not runtime:
        raise ValueError("runtime_instance_id is required")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= 0:
        raise ValueError("sequence must be a positive integer")
    sha = _exact_sha(repo_sha)
    if not packets:
        raise ValueError("at least one options-intelligence packet is required")

    normalized: dict[str, object] = {}
    for raw_symbol, packet in packets.items():
        symbol = _canonical_us_symbol(raw_symbol)
        packet_symbol = _canonical_us_symbol(packet.current_gex.underlying_symbol)
        if symbol != packet_symbol:
            raise ValueError("snapshot key must match packet underlying symbol")

        payload = packet.to_payload()
        if payload.get("trading_authority") is not False:
            raise ValueError("options packet trading_authority must remain false")
        if payload.get("live_trade") is not False:
            raise ValueError("options packet live_trade must remain false")
        if payload.get("decision_permission") != "BLOCKED_V0_1":
            raise ValueError("options packet decision permission must remain blocked")
        normalized[symbol] = payload

    return {
        "schema": SCHEMA,
        "runtime_instance_id": runtime,
        "repo_sha": sha,
        "sequence": sequence,
        "emitted_at_utc": _iso(emitted_at_utc),
        "research_only": True,
        "trading_authority": False,
        "live_trade": False,
        "symbols": normalized,
    }


def write_options_intelligence_runtime_snapshot(
    path: str | os.PathLike[str],
    payload: Mapping[str, object],
) -> None:
    """Atomically persist a JSON options-intelligence sidecar."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, destination)

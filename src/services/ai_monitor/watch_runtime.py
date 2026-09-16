"""Durable USER_PINNED truth for the AI Monitor Active Watch Universe.

This module owns only persistence of user-pinned watch membership. It does not
discover/rank Radar candidates, mutate LiveFeed desired subscriptions, interpret
market structure, grant Entry Permission, or place orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Optional, Protocol, Sequence
from uuid import uuid4

from .watch_universe import ActiveWatchUniverse, WatchIdentity


class WatchRuntimeError(RuntimeError):
    """Base error for durable-watch persistence failures."""


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc_text(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("persisted activation timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, order=True)
class PersistedUserPin:
    identity: WatchIdentity
    activated_at: datetime

    def __post_init__(self) -> None:
        if self.activated_at.tzinfo is None:
            raise ValueError("activated_at must be timezone-aware")


class UserPinStore(Protocol):
    def load(self) -> tuple[PersistedUserPin, ...]:
        ...

    def replace(self, pins: Sequence[PersistedUserPin]) -> None:
        ...


class JsonUserPinStore:
    """Atomic, single-writer durable store for USER_PINNED truth.

    A dedicated file avoids expanding the shared production DB schema in this
    landing slice. AI Monitor remains the single writer for this store.
    """

    VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def load(self) -> tuple[PersistedUserPin, ...]:
        with self._lock:
            return self._load_unlocked()

    def _load_unlocked(self) -> tuple[PersistedUserPin, ...]:
        if not self.path.exists():
            return ()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WatchRuntimeError("cannot read durable user-pin truth") from exc
        if not isinstance(payload, dict):
            raise WatchRuntimeError("invalid user-pin store payload")
        if payload.get("version") != self.VERSION:
            raise WatchRuntimeError("unsupported user-pin store version")
        rows = payload.get("pins")
        if not isinstance(rows, list):
            raise WatchRuntimeError("invalid user-pin store payload")
        pins: dict[WatchIdentity, PersistedUserPin] = {}
        try:
            for row in rows:
                if not isinstance(row, dict):
                    raise WatchRuntimeError("invalid user-pin row")
                identity = WatchIdentity(market=row.get("market", ""), symbol=row.get("symbol", ""))
                pin = PersistedUserPin(
                    identity=identity,
                    activated_at=_parse_utc_text(row.get("activated_at", "")),
                )
                pins[identity] = pin
        except (TypeError, ValueError) as exc:
            raise WatchRuntimeError("invalid durable user-pin truth") from exc
        return tuple(pins[key] for key in sorted(pins))

    def replace(self, pins: Sequence[PersistedUserPin]) -> None:
        with self._lock:
            canonical = {pin.identity: pin for pin in pins}
            payload = {
                "version": self.VERSION,
                "pins": [
                    {
                        "market": pin.identity.market,
                        "symbol": pin.identity.symbol,
                        "activated_at": _utc_text(pin.activated_at),
                    }
                    for pin in (canonical[key] for key in sorted(canonical))
                ],
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
            data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            try:
                with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            except OSError as exc:
                raise WatchRuntimeError("cannot persist durable user-pin truth") from exc
            finally:
                if temporary.exists():
                    temporary.unlink()


class DurableUserPins:
    """Persist USER_PINNED state before changing in-memory watch membership."""

    def __init__(self, store: UserPinStore) -> None:
        self.store = store
        self._lock = threading.RLock()

    def restore(self, universe: ActiveWatchUniverse) -> tuple[PersistedUserPin, ...]:
        pins = self.store.load()
        for pin in pins:
            universe.pin(
                market=pin.identity.market,
                symbol=pin.identity.symbol,
                activated_at=pin.activated_at,
            )
        return pins

    def pin(
        self,
        universe: ActiveWatchUniverse,
        *,
        market: str,
        symbol: str,
        activated_at: Optional[datetime] = None,
    ) -> PersistedUserPin:
        timestamp = activated_at or datetime.now(timezone.utc)
        identity = WatchIdentity(market=market, symbol=symbol)
        with self._lock:
            existing = {pin.identity: pin for pin in self.store.load()}
            pin = existing.get(identity) or PersistedUserPin(identity=identity, activated_at=timestamp)
            existing[identity] = pin
            self.store.replace(tuple(existing.values()))
            universe.pin(
                market=identity.market,
                symbol=identity.symbol,
                activated_at=pin.activated_at,
            )
            return pin

    def unpin(self, universe: ActiveWatchUniverse, *, market: str, symbol: str) -> None:
        identity = WatchIdentity(market=market, symbol=symbol)
        with self._lock:
            existing = {pin.identity: pin for pin in self.store.load()}
            existing.pop(identity, None)
            self.store.replace(tuple(existing.values()))
            universe.unpin(market=identity.market, symbol=identity.symbol)

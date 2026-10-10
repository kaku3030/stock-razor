"""Pure parser for read-only external paper-account discovery evidence.

The OpenD/Futu call remains outside this module.  This parser accepts the
sanitized rows returned by a read-only account-list probe and emits only the
minimum non-secret evidence needed by the external simulator contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping, Sequence


class AccountDiscoveryBlocked(RuntimeError):
    """Raised when account mode or identity cannot be proven unambiguously."""


class AccountMode(StrEnum):
    SIMULATE = "SIMULATE"
    REAL = "REAL"


@dataclass(frozen=True)
class SimulatedAccountDiscovery:
    account_id: str
    mode: AccountMode
    market: str
    authenticated: bool
    observed_at: datetime


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AccountDiscoveryBlocked(f"{field} is required")
    return value.strip()


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AccountDiscoveryBlocked(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _mode(value: object) -> AccountMode:
    try:
        return AccountMode(str(value).upper())
    except ValueError as exc:
        raise AccountDiscoveryBlocked("account mode is unsupported") from exc


def discover_simulated_us_account(
    rows: Sequence[Mapping[str, object]],
    *,
    observed_at: datetime,
) -> SimulatedAccountDiscovery:
    """Select exactly one authenticated US SIMULATE account from sanitized rows."""

    timestamp = _utc(observed_at, "observed_at")
    candidates: list[SimulatedAccountDiscovery] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise AccountDiscoveryBlocked("account row is malformed")
        account_id = _text(row.get("acc_id"), "acc_id")
        mode = _mode(row.get("trd_env"))
        market = _text(row.get("market"), "market").upper()
        authenticated = row.get("authenticated") is True
        if mode is AccountMode.SIMULATE and market == "US" and authenticated:
            candidates.append(
                SimulatedAccountDiscovery(
                    account_id=account_id,
                    mode=mode,
                    market=market,
                    authenticated=True,
                    observed_at=timestamp,
                )
            )

    if len(candidates) != 1:
        raise AccountDiscoveryBlocked(
            "expected exactly one authenticated US SIMULATE account"
        )
    return candidates[0]

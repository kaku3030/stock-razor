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


def discover_futu_us_stock_sim_account(
    rows: Sequence[Mapping[str, object]],
    *,
    expected_account_id: str,
    observed_at: datetime,
    session_authenticated: bool = False,
) -> SimulatedAccountDiscovery:
    """Match exactly one ACTIVE US stock Paper account from official Futu rows.

    This parses an already completed read-only get_acc_list call, never opens
    OpenD. The caller must independently prove the transport/session and
    preselect the expected account ID out of band. IDs are not safe to log.

    No order or even Paper adapter permission follows from a successful parse.
    Position, buying power, open orders and fills still require reconciliation.
    """
    timestamp = _utc(observed_at, "observed_at")
    if session_authenticated is not True:
        raise AccountDiscoveryBlocked("OpenD authenticated session not independently verified")
    if (
        not isinstance(expected_account_id, str)
        or not expected_account_id.isascii()
        or not expected_account_id.isdigit()
        or not 1 <= len(expected_account_id) <= 32
    ):
        raise AccountDiscoveryBlocked("expected numeric account identity is required")
    if not isinstance(rows, (list, tuple)):
        raise AccountDiscoveryBlocked("account list must be a sequence")
    matches: list[SimulatedAccountDiscovery] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise AccountDiscoveryBlocked("account row is malformed")
        raw_id = row.get("acc_id")
        if type(raw_id) is int:
            candidate_id = str(raw_id) if raw_id > 0 else ""
        elif isinstance(raw_id, str) and raw_id.isascii() and raw_id.isdigit():
            candidate_id = raw_id
        else:
            candidate_id = ""
        if candidate_id != expected_account_id:
            continue
        mode = row.get("trd_env")
        auth = row.get("trdmarket_auth")
        kind = row.get("sim_acc_type")
        status = row.get("acc_status")
        if not (
            isinstance(mode, str) and mode.upper() == "SIMULATE"
            and isinstance(auth, (list, tuple))
            and "US" in [item.upper() for item in auth if isinstance(item, str)]
            and isinstance(kind, str)
            and kind.upper() == "STOCK_AND_OPTION"
            and isinstance(status, str) and status.upper() == "ACTIVE"
        ):
            raise AccountDiscoveryBlocked("expected account is not an active US stock SIMULATE account")
        matches.append(
            SimulatedAccountDiscovery(
                account_id=candidate_id,
                mode=AccountMode.SIMULATE,
                market="US",
                authenticated=True,
                observed_at=timestamp,
            )
        )
    if len(matches) != 1:
        raise AccountDiscoveryBlocked("exact simulated account identity not verified")
    return matches[0]

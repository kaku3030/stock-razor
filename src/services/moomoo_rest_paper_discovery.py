"""Schema-only, offline parser for moomoo's new REST simulated account list.

Official docs (research only):
https://open.moomoo.com/api/sim-trade/account-list

GET /api/v1.0/sim-trade/accounts may automatically CREATE accounts on first
call. This module DOES NOT make that request, perform OAuth, register a client,
store tokens, assume Japan entitlement, or submit/modify any orders.
The legacy OpenD account and mobile Paper account may be different.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

US_MARKET_ID = 2
MAX_ROWS = 1000
MAX_AGE_SECONDS = 60


class RestPaperDiscoveryBlocked(RuntimeError):
    """Schema, approval, or identity proof is missing; avoid raw account IDs."""


@dataclass(frozen=True)
class RestPaperUSAccountCandidate:
    account_id: str
    observed_at_utc: datetime
    market_id: int = US_MARKET_ID
    provider: str = "MOOMOO_REST_SIM_PAPER"
    schema_checked_only: bool = True
    rest_user_authorization_independently_verified: bool = False
    japan_account_entitlement_verified: bool = False
    legacy_opend_account_parity_verified: bool = False
    mobile_paper_account_parity_verified: bool = False
    paper_auto_ready: bool = False
    external_order_allowed: bool = False
    live_trade: bool = False


def _numeric_id(value: object) -> bool:
    return (
        isinstance(value, str) and value.isascii() and value.isdigit()
        and 1 <= len(value) <= 32
    )


def inspect_rest_us_sim_account_list(
    response: Mapping[str, object],
    *,
    expected_account_id: str,
    observed_at_utc: datetime,
    now_utc: datetime,
    read_scope_confirmed: bool = False,
    first_read_side_effect_approved: bool = False,
) -> RestPaperUSAccountCandidate:
    """Validate *already obtained* REST account-list JSON; never perform I/O.

    Both boolean flags are explicit out-of-band acceptance inputs. They are
    not an independent proof of REST OAuth identity or app/mobile parity.
    """
    if (
        read_scope_confirmed is not True
        or first_read_side_effect_approved is not True
    ):
        raise RestPaperDiscoveryBlocked("read-only OAuth scope or first-read approval missing")
    if (
        not isinstance(observed_at_utc, datetime)
        or observed_at_utc.tzinfo is None
        or observed_at_utc.utcoffset() is None
        or not isinstance(now_utc, datetime)
        or now_utc.tzinfo is None
        or now_utc.utcoffset() is None
    ):
        raise RestPaperDiscoveryBlocked("timezone-aware REST observation is required")
    observed = observed_at_utc.astimezone(timezone.utc)
    age = (now_utc.astimezone(timezone.utc) - observed).total_seconds()
    if not 0 <= age <= MAX_AGE_SECONDS:
        raise RestPaperDiscoveryBlocked("REST account observation future or stale")
    if not _numeric_id(expected_account_id):
        raise RestPaperDiscoveryBlocked("exact numeric expected account ID is required")
    if not isinstance(response, Mapping):
        raise RestPaperDiscoveryBlocked("REST response is malformed")
    # True == 1 in Python; never admit bool as an API success code.
    if type(response.get("ret_code")) is not int or response["ret_code"] != 0:
        raise RestPaperDiscoveryBlocked("REST account API has not succeeded")
    data = response.get("data")
    if not isinstance(data, Mapping):
        raise RestPaperDiscoveryBlocked("REST account response lacks data")
    rows = data.get("accounts")
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise RestPaperDiscoveryBlocked("REST account list shape or size invalid")
    matches = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise RestPaperDiscoveryBlocked("REST account row malformed")
        candidate = row.get("account_id")
        market_id = row.get("market_id")
        if candidate != expected_account_id:
            continue
        if not _numeric_id(candidate) or type(market_id) is not int or market_id != US_MARKET_ID:
            raise RestPaperDiscoveryBlocked("expected REST account is not US simulated")
        # Metadata is not an identity substitute: never accept account_title.
        if type(row.get("broker_id")) is not int or type(row.get("account_type")) is not int:
            raise RestPaperDiscoveryBlocked("expected REST account metadata invalid")
        matches += 1
    if matches != 1:
        raise RestPaperDiscoveryBlocked("exactly one matching US REST simulated account required")
    return RestPaperUSAccountCandidate(
        account_id=expected_account_id, observed_at_utc=observed,
    )

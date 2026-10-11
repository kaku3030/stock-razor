"""Offline moomoo OpenAPI OAuth scope gate, NOT token validation.

Vendor docs: https://open.moomoo.com/mcp-docs/authentication
and https://open.moomoo.com/api/overview/getting-started

MCP and REST routes can expose REAL trading capabilities. Never grant
trade:write, quote:write or wildcard accid:* to a read-only Radar connector.
This contract has no OAuth client, SDK, HTTP, token or broker IO.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re

EXACT_ID = re.compile(r"^[0-9]{1,32}$", flags=re.ASCII)
ALLOWED_SCOPES = frozenset(("quote:read", "trade:read"))
ACCOUNT_PREFIX = "accid:"


class MoomooOAuthPilotMode(StrEnum):
    QUOTE_ONLY = "QUOTE_ONLY"
    ACCOUNT_READBACK = "ACCOUNT_READBACK"


@dataclass(frozen=True)
class MoomooReadOnlyScopeGate:
    """Only reports structural request/grant consistency, not API entitlement."""

    scoped_input_status: str
    reasons: tuple[str, ...]
    quote_read_requested: bool
    trade_read_requested: bool
    research_only: bool = True
    oauth_session_independently_verified: bool = False
    account_entitlement_verified: bool = False
    mobile_paper_account_parity_verified: bool = False
    first_get_side_effect_approved: bool = False
    paper_auto_ready: bool = False
    provider_io_allowed: bool = False
    broker_mutation_allowed: bool = False
    live_trade: bool = False


def assess_moomoo_readonly_oauth_grant(
    grant_scope: str,
    *,
    pilot_mode: MoomooOAuthPilotMode,
    expected_account_id: str | None = None,
) -> MoomooReadOnlyScopeGate:
    """Fail closed on any write, wildcard or unspecified account permission.

    Use on *already supplied* OAuth grant metadata. The server must verify
    issuer, TLS, state, PKCE and token authority independently. In particular,
    this function never implies a user's Japan account is API eligible.
    """

    reasons: set[str] = set()
    if not isinstance(pilot_mode, MoomooOAuthPilotMode):
        reasons.add("PILOT_MODE_UNSUPPORTED")
    if not isinstance(grant_scope, str) or not grant_scope or len(grant_scope) > 2048:
        tokens: list[str] = []
        reasons.add("GRANT_SCOPE_MISSING_OR_INVALID")
    else:
        tokens = grant_scope.split()
        if not tokens or len(tokens) != len(set(tokens)):
            reasons.add("GRANT_SCOPES_EMPTY_OR_DUPLICATED")
    granted = set(tokens)
    if any("write" in item for item in granted) or "trade:write" in granted or "quote:write" in granted:
        reasons.add("WRITE_SCOPE_PRESENT")
    unknown = [
        item for item in granted
        if item not in ALLOWED_SCOPES and not item.startswith(ACCOUNT_PREFIX)
    ]
    if unknown:
        reasons.add("UNRECOGNIZED_SCOPE_PRESENT")
    account_scopes = [item[len(ACCOUNT_PREFIX):] for item in granted if item.startswith(ACCOUNT_PREFIX)]
    if any(not EXACT_ID.fullmatch(value) for value in account_scopes):
        reasons.add("WILDCARD_OR_INVALID_ACCOUNT_SCOPE")
    if "quote:read" not in granted:
        reasons.add("QUOTE_READ_MISSING")
    if pilot_mode is MoomooOAuthPilotMode.QUOTE_ONLY:
        if "trade:read" in granted or account_scopes:
            reasons.add("QUOTE_ONLY_HAS_ACCOUNT_ACCESS")
    elif pilot_mode is MoomooOAuthPilotMode.ACCOUNT_READBACK:
        if "trade:read" not in granted:
            reasons.add("ACCOUNT_READBACK_TRADE_READ_MISSING")
        if (
            not isinstance(expected_account_id, str)
            or not EXACT_ID.fullmatch(expected_account_id)
            or account_scopes != [expected_account_id]
        ):
            reasons.add("EXACT_ACCOUNT_SCOPE_NOT_PROVEN")

    return MoomooReadOnlyScopeGate(
        scoped_input_status="SCOPED_INPUTS_CONSISTENT" if not reasons else "BLOCKED",
        reasons=tuple(sorted(reasons)),
        quote_read_requested="quote:read" in granted,
        trade_read_requested="trade:read" in granted,
    )

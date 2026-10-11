"""Offline, deny-by-default catalog filter for the official moomoo remote MCP.

This module never connects to `https://mcp.moomoo.com/mcp`, calls a tool,
authenticates, observes accounts, or places any order. It classifies *tool
names only*. Catalog approval is explicitly NOT execution authorization,
because tool schemas, OAuth issuer and provider-side semantics can change.

Vendor docs: https://open.moomoo.com/mcp-docs/available-tools
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

# Fixed subsets of publicly documented names; no fuzzy prefixes, regex
# shortcuts or automatic approval for "get"/"read"/"list" named methods.
# All quote tools here are observational/research-only.
QUOTE_READ_SHADOW = frozenset((
    "quote_future_info", "quote_economic_calendar_hot",
    "quote_stock_feed", "quote_community_search",
))
SIM_ACCOUNT_READ_SHADOW = frozenset((
    "sim_trade_cash_info", "sim_trade_position_list",
    "sim_trade_history_order_list",
))
# This is a GET in REST but creates simulated accounts on first request;
# treat the MCP name as unreviewed for side effects until proven otherwise.
FIRST_READ_SIDE_EFFECT = frozenset(("sim_trade_account_list",))
MUTATING_NAMES = frozenset((
    "sim_trade_input_order", "sim_trade_modify_order", "sim_trade_cancel_order",
    "trading_order_place", "trading_order_replace", "trading_order_cancel",
    "crypto_account_create_order", "crypto_account_cancel_order",
))


class RemoteMcpInventoryMode(StrEnum):
    QUOTE_ONLY = "QUOTE_ONLY"
    SIM_ACCOUNT_RESEARCH = "SIM_ACCOUNT_RESEARCH"


@dataclass(frozen=True)
class RemoteMcpInventory:
    status: str
    candidate_quote_tools: tuple[str, ...]
    candidate_paper_read_tools: tuple[str, ...]
    blocked_first_read_side_effect_count: int
    blocked_mutation_count: int
    blocked_unknown_count: int
    seen_count: int
    live_provider_tool_schemas_verified: bool = False
    oauth_session_verified: bool = False
    first_read_side_effect_approved: bool = False
    tool_invocation_allowed: bool = False
    account_mutation_allowed: bool = False
    real_trade_allowed: bool = False


def classify_moomoo_mcp_catalog(
    names: Sequence[str],
    *,
    mode: RemoteMcpInventoryMode = RemoteMcpInventoryMode.QUOTE_ONLY,
) -> RemoteMcpInventory:
    """Read *already discovered* public tool names without invoking them.

    A candidate must still have a verified remote TLS/authenticated MCP
    session, manually reviewed live JSON schema and exact input scope.
    """

    if (
        not isinstance(mode, RemoteMcpInventoryMode)
        or not isinstance(names, (list, tuple))
        or len(names) > 1000
        or any(
            not isinstance(v, str)
            or not 1 <= len(v) <= 120
            or not v.isascii()
            or not all(c.isalnum() or c == "_" for c in v)
            for v in names
        )
        or len(set(names)) != len(names)
    ):
        return RemoteMcpInventory(
            status="INVALID_OR_DUPLICATE_CATALOG",
            candidate_quote_tools=(),
            candidate_paper_read_tools=(),
            blocked_first_read_side_effect_count=0,
            blocked_mutation_count=0,
            blocked_unknown_count=0,
            seen_count=0,
        )

    allowed = set(QUOTE_READ_SHADOW)
    if mode is RemoteMcpInventoryMode.SIM_ACCOUNT_RESEARCH:
        allowed.update(SIM_ACCOUNT_READ_SHADOW)
    q = tuple(sorted(name for name in names if name in QUOTE_READ_SHADOW))
    paper = tuple(sorted(name for name in names if name in SIM_ACCOUNT_READ_SHADOW and name in allowed))
    side_effect = sum(name in FIRST_READ_SIDE_EFFECT for name in names)
    mutations = sum(name in MUTATING_NAMES for name in names)
    unknown = sum(
        name not in QUOTE_READ_SHADOW
        and name not in SIM_ACCOUNT_READ_SHADOW
        and name not in FIRST_READ_SIDE_EFFECT
        and name not in MUTATING_NAMES
        for name in names
    )
    # Denied items in catalog do not disappear from vendor's server; our
    # future client MUST enforce this as a call-time allowlist too.
    return RemoteMcpInventory(
        status="SHADOW_CATALOG_ONLY_NO_INVOCATION",
        candidate_quote_tools=q,
        candidate_paper_read_tools=paper,
        blocked_first_read_side_effect_count=side_effect,
        blocked_mutation_count=mutations,
        blocked_unknown_count=unknown + (sum(name in SIM_ACCOUNT_READ_SHADOW for name in names) if mode is RemoteMcpInventoryMode.QUOTE_ONLY else 0),
        seen_count=len(names),
    )

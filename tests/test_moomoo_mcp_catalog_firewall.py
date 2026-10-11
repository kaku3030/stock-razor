"""Official moomoo MCP tool discovery cannot automatically grant calls."""

from src.services.moomoo_mcp_catalog_firewall import (
    RemoteMcpInventoryMode,
    classify_moomoo_mcp_catalog,
)


def test_quote_only_uses_exact_small_candidates_not_live_account_tools():
    r = classify_moomoo_mcp_catalog([
        "quote_future_info", "quote_economic_calendar_hot",
        "sim_trade_cash_info", "account_positions",
        "trading_order_place", "sim_trade_account_list",
        "sim_trade_input_order",
    ])
    assert r.candidate_quote_tools == (
        "quote_economic_calendar_hot", "quote_future_info",
    )
    assert r.candidate_paper_read_tools == ()
    assert r.blocked_first_read_side_effect_count == 1
    assert r.blocked_mutation_count == 2
    assert r.blocked_unknown_count == 2
    assert r.tool_invocation_allowed is False
    assert r.account_mutation_allowed is False
    assert r.real_trade_allowed is False
    assert r.oauth_session_verified is False


def test_paper_readback_mode_excludes_account_listing_and_all_trading():
    r = classify_moomoo_mcp_catalog([
        "sim_trade_cash_info", "sim_trade_position_list",
        "sim_trade_history_order_list", "sim_trade_account_list",
        "sim_trade_modify_order", "account_authorized_trd_accs",
    ], mode=RemoteMcpInventoryMode.SIM_ACCOUNT_RESEARCH)
    assert r.candidate_paper_read_tools == (
        "sim_trade_cash_info", "sim_trade_history_order_list",
        "sim_trade_position_list",
    )
    assert r.blocked_first_read_side_effect_count == 1
    assert r.blocked_mutation_count == 1
    assert r.blocked_unknown_count == 1
    assert r.tool_invocation_allowed is False
    assert r.first_read_side_effect_approved is False


def test_unknown_or_misleading_names_do_not_get_fuzzy_permission():
    r = classify_moomoo_mcp_catalog([
        "get_all_trading_orders", "read_and_place_order",
        "quote_future_info_clone", "QUOTE_FUTURE_INFO",
    ])
    assert r.candidate_quote_tools == ()
    assert r.blocked_unknown_count == 4


def test_untrusted_tool_catalog_validation_blocks_duplicates_and_objects():
    for payload in (
        ["quote_future_info", "quote_future_info"],
        ["quote_future_info", None],
        ["quote_future_info", 7],
        ["quote_future_info", "工具"],
        [""],
        list(range(1001)),
        "quote_future_info",
    ):
        result = classify_moomoo_mcp_catalog(payload)
        assert result.status == "INVALID_OR_DUPLICATE_CATALOG"
        assert result.tool_invocation_allowed is False


def test_unsupported_mode_is_rejected():
    r = classify_moomoo_mcp_catalog(["quote_future_info"], mode="REAL_TRADE")
    assert r.status == "INVALID_OR_DUPLICATE_CATALOG"
    assert r.real_trade_allowed is False

"""Compatibility gate: existing frozen ChatGPT CN action supports compact read."""
from unittest.mock import Mock

from realtime_monitor import readonly_mcp_server as server


def test_exact_compat_sentinel_uses_existing_readonly_quick_scan(monkeypatch):
    compact = {
        "status": "RESEARCH_ONLY",
        "research_only": True,
        "can_confirm_signal": False,
        "entry_gate": "ENTRY_BLOCKED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "provider_requests": 0,
        "symbols": {},
    }
    quick = Mock(return_value=compact)
    original = Mock()
    monkeypatch.setattr(server, "read_cn_quick_scan", quick)
    monkeypatch.setattr(server, "read_cn_radar_analysis", original)
    assert server.get_cn_market_analysis(["__QUICK_SCAN__"]) is compact
    quick.assert_called_once_with()
    original.assert_not_called()


def test_default_and_real_symbols_remain_identical(monkeypatch):
    original = Mock(side_effect=lambda arg: {"legacy_input": arg})
    quick = Mock()
    monkeypatch.setattr(server, "read_cn_radar_analysis", original)
    monkeypatch.setattr(server, "read_cn_quick_scan", quick)
    for symbols in (None, [], ["159611"], ["159611", "512730"],
                    ["__QUICK_SCAN__", "159611"], ["__quick_scan__"],
                    ["__QUICK_SCAN__ "], ["invalid_symbol"]):
        assert server.get_cn_market_analysis(symbols) == {"legacy_input": symbols}
    assert original.call_count == 8
    quick.assert_not_called()


def test_quick_failure_is_not_upgraded_to_trade_permission(monkeypatch):
    blocked = {
        "status": "BLOCKED",
        "reasons": ["SOURCE_IDENTITY_MISMATCH"],
        "research_only": True,
        "can_confirm_signal": False,
        "entry_gate": "ENTRY_BLOCKED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }
    quick = Mock(return_value=blocked)
    monkeypatch.setattr(server, "read_cn_quick_scan", quick)
    assert server.get_cn_market_analysis(["__QUICK_SCAN__"]) is blocked
    assert blocked["entry_gate"] == "ENTRY_BLOCKED"
    assert blocked["status"] == "BLOCKED"

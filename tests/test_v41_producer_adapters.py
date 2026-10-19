from data_provider.cn_fast_research_brief import build_cn_main_control_report_v41
from data_provider.us_fast_research_brief import build_us_main_control_report_v41


def test_cn_producer_adapter_cannot_be_spoofed_into_another_provider():
    result = build_cn_main_control_report_v41("600000", endpoint_evidence=None)
    assert result["status"] == "BLOCKED"
    assert result["provider"] == "TickFlow"
    assert result["timeframes"] == ["1m", "5m", "15m", "1H", "D1"]
    assert result["safety"]["live_trade"] is False
    assert result["opportunities"] == []


def test_us_producer_adapter_cannot_be_spoofed_into_another_provider():
    result = build_us_main_control_report_v41("AAPL", endpoint_evidence=None)
    assert result["status"] == "BLOCKED"
    assert result["provider"] == "OpenD"
    assert result["timeframes"] == ["1m", "5m", "15m", "1H", "D1"]
    assert result["safety"]["radar_admission"] == "BLOCKED"
    assert result["conditional_plans"] == []

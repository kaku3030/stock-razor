"""Cloud CN gold-ETF watchlist is bounded and benchmark-aligned."""

from pathlib import Path


INSTALLER = Path("ops/aws/install_cn_eastmoney_observer.sh").read_text(encoding="utf-8")
BENCHMARK = Path(".github/workflows/benchmark-cloud-fast-path-readonly.yml").read_text(encoding="utf-8")


def test_cn_observer_defaults_cover_benchmark_gold_etf():
    expected = "512730,159611,159363,518880"
    assert 'SYMBOLS="${SYMBOLS:-' + expected + '}"' in INSTALLER
    assert '"' + expected + '",' in INSTALLER
    assert "--symbols 159611 518880" in BENCHMARK
    assert set(expected.split(",")) == {"512730", "159611", "159363", "518880"}


def test_watchlist_extension_keeps_research_and_admission_isolated():
    assert "stock-razor-cn-eastmoney.service" in INSTALLER
    assert "RADAR_ADMISSION=BLOCKED" in INSTALLER
    assert "LIVE_TRADE=NO" in INSTALLER
    assert "OpenUSTradeContext" not in INSTALLER
    assert "OpenSecTradeContext" not in INSTALLER

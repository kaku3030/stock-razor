from datetime import datetime, timezone

import pytest

from scripts import run_stock_radar_technical_state as runner
from src.storage import DatabaseManager


NOW = datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc)


def setup_function() -> None:
    DatabaseManager.reset_instance()


def teardown_function() -> None:
    DatabaseManager.reset_instance()


def test_script_run_uses_injected_read_only_adapters(tmp_path, monkeypatch) -> None:
    captured = {}

    class FakeRuntime:
        def __init__(self, intraday, daily, *, radar):
            captured["adapters"] = (intraday, daily)
            captured["radar"] = radar

        def run(self, **kwargs):
            captured["arguments"] = kwargs
            return {
                "research_only": True,
                "runtime": {"evaluated_count": 1},
            }

    intraday = object()
    daily = object()
    monkeypatch.setattr(runner, "StockRadarProviderRuntime", FakeRuntime)

    result = runner.run(
        provider="alpaca",
        market="us",
        symbols=["NVDA"],
        run_id="run-1",
        output_dir=tmp_path,
        database=tmp_path / "runtime.db",
        as_of=NOW,
        intraday_adapter=intraday,
        daily_adapter=daily,
    )

    assert result["runtime"]["evaluated_count"] == 1
    assert result["research_only"] is True
    assert captured["adapters"] == (intraday, daily)
    assert captured["arguments"]["run_id"] == "run-1"


def test_script_rejects_provider_market_mismatch_before_runtime(tmp_path) -> None:
    with pytest.raises(ValueError, match="requires market cn"):
        runner.run(
            provider="qmt",
            market="us",
            symbols=["600519"],
            run_id="run-1",
            output_dir=tmp_path,
            database=tmp_path / "runtime.db",
            intraday_adapter=object(),
            daily_adapter=object(),
        )


def test_cn_radar_defaults_to_historical_adapter_for_daily_bars(tmp_path, monkeypatch) -> None:
    captured = {}

    class FakeRuntime:
        def __init__(self, intraday, daily, *, radar):
            captured["adapters"] = (intraday, daily)

        def run(self, **kwargs):
            return {"runtime": {"evaluated_count": 1}}

    historical = object()
    monkeypatch.setattr(runner, "StockRadarProviderRuntime", FakeRuntime)
    monkeypatch.setattr(runner, "StockDataHubHistoricalAdapter", lambda: historical)

    runner.run(
        provider="eastmoney",
        market="cn",
        symbols=["600519"],
        run_id="run-cn-history",
        output_dir=tmp_path,
        database=tmp_path / "runtime.db",
        intraday_adapter=object(),
        daily_adapter=None,
        as_of=NOW,
    )

    assert captured["adapters"][1] is historical

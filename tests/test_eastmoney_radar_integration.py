import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from data_provider.eastmoney_gm_market_data_adapter import EastmoneyGMMarketDataAdapter
from src.repositories.stock_radar_technical_state_repo import StockRadarTechnicalStateRepository
from src.services.stock_radar_v2.config import RuntimeConfig
from src.services.stock_radar_v2.provider_runtime import StockRadarProviderRuntime
from src.services.stock_radar_v2.technical_state_radar import StockRadarTechnicalStateRadar
from src.storage import DatabaseManager


NOW = datetime(2026, 9, 30, 2, 30, tzinfo=timezone.utc)


class FakeEastmoneyGM:
    def history_n(self, **kwargs):
        end = datetime(2026, 9, 30, 10, 30)
        frequency = kwargs["frequency"]
        if frequency == "1m":
            return pd.DataFrame([
                {
                    "bob": (end - timedelta(minutes=index + 1)).strftime("%Y-%m-%d %H:%M"),
                    "eob": (end - timedelta(minutes=index)).strftime("%Y-%m-%d %H:%M"),
                    "open": 100 + index / 10,
                    "high": 101 + index / 10,
                    "low": 99 + index / 10,
                    "close": 100.5 + index / 10,
                    "volume": 1000 + index,
                    "amount": 100000 + index,
                }
                for index in range(60)
            ])
        if frequency in {"15m", "60m"}:
            step = 15 if frequency == "15m" else 60
            return pd.DataFrame([
                {
                    "bob": (end - timedelta(minutes=step * (index + 1))).strftime("%Y-%m-%d %H:%M"),
                    "eob": (end - timedelta(minutes=step * index)).strftime("%Y-%m-%d %H:%M"),
                    "open": 100 + index / 10,
                    "high": 101 + index / 10,
                    "low": 99 + index / 10,
                    "close": 100.5 + index / 10,
                    "volume": 1000 + index,
                    "amount": 100000 + index,
                }
                for index in range(60)
            ])
        if frequency == "1d":
            return pd.DataFrame([
                {
                    "bob": f"2026-09-{28 + index:02d} 00:00",
                    "eob": f"2026-09-{28 + index:02d} 00:00",
                    "open": 100 + index,
                    "high": 101 + index,
                    "low": 99 + index,
                    "close": 100.5 + index,
                    "volume": 1000 + index,
                    "amount": 100000 + index,
                }
                for index in range(3)
            ])
        raise AssertionError(f"unexpected frequency {frequency}")

    def history(self, **kwargs):
        return self.history_n(**kwargs)

    def current(self, **kwargs):
        return [{"last_price": 106, "volume": 2000, "amount": 200000}]


def setup_function() -> None:
    DatabaseManager.reset_instance()


def teardown_function() -> None:
    DatabaseManager.reset_instance()


def test_eastmoney_adapter_flows_through_radar_and_read_only_export(tmp_path) -> None:
    adapter = EastmoneyGMMarketDataAdapter(FakeEastmoneyGM(), now=lambda: NOW)
    db = DatabaseManager(db_url=f"sqlite:///{tmp_path / 'runtime.db'}")
    radar = StockRadarTechnicalStateRadar(StockRadarTechnicalStateRepository(db))
    runtime = StockRadarProviderRuntime(
        adapter,
        adapter,
        radar=radar,
        config=RuntimeConfig(
            minute_history_limit=60,
            history_lookback_days=30,
            daily_history_limit=3,
            freshness_limit_seconds=120,
        ),
        now=lambda: NOW,
    )

    result = runtime.run(
        market="cn",
        run_id="eastmoney-integration-1",
        symbols=["600519.SH"],
        output_dir=tmp_path,
        as_of=NOW,
    )

    export = json.loads((tmp_path / "cn_stock_radar_read_only_market_facts.json").read_text("utf-8"))
    assert result["runtime"]["evaluated_count"] == 1
    assert result["research_only"] is True
    assert export["schema"] == "stock-razor-read-only-market-facts-v1"
    assert export["trading_capability"] is False
    observed = {bar["timeframe"] for bar in export["facts"][0]["bars"]}
    assert {"15m", "60m", "1d"}.issubset(observed)
    assert export["facts"][0]["current"]["price"] == 106
    assert result["runtime"]["timing"][0]["data_fetch_ms"] >= 0
    assert result["runtime"]["timing"][0]["analysis_ms"] >= 0
    assert export["facts"][0]["timing"]["total_ms"] >= 0
    sample = export["facts"][0]["bars"][0]
    assert {"symbol", "bob", "eob", "open", "high", "low", "close", "volume", "amount",
            "provider", "freshness_ms", "currentness", "quality", "status"}.issubset(sample)

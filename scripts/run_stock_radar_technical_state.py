"""Run one read-only QMT or Alpaca technical-state radar publication."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_provider.base import DataFetcherManager
from data_provider.alpaca_market_data_adapter import AlpacaMarketDataAdapter, AlpacaRestMarketDataClient
from data_provider.existing_market_data_adapter import ExistingMarketDataAdapter
from data_provider.market_data_adapter import MarketDataAdapter
from src.repositories.stock_radar_technical_state_repo import StockRadarTechnicalStateRepository
from src.services.stock_radar_v2.provider_runtime import StockRadarProviderRuntime
from src.services.stock_radar_v2.technical_state_radar import StockRadarTechnicalStateRadar
from src.storage import DatabaseManager


def _intraday_adapter(provider: str, *, alpaca_feed: str) -> MarketDataAdapter:
    if provider == "qmt":
        try:
            from xtquant import xtdata
        except ImportError as exc:
            raise RuntimeError("xtquant is not installed in this Python environment") from exc
        from data_provider.xtquant_market_data_adapter import XtquantMarketDataAdapter

        return XtquantMarketDataAdapter(xtdata)

    api_key = os.getenv("APCA_API_KEY_ID", "").strip()
    api_secret = os.getenv("APCA_API_SECRET_KEY", "").strip()
    if not api_key or not api_secret:
        raise RuntimeError("APCA_API_KEY_ID and APCA_API_SECRET_KEY are required for Alpaca market data")
    return AlpacaMarketDataAdapter(
        AlpacaRestMarketDataClient(api_key, api_secret),
        feed=alpaca_feed,
    )


def _database_manager(path: Path) -> DatabaseManager:
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return DatabaseManager(db_url=f"sqlite:///{resolved.as_posix()}")


def run(
    *,
    provider: str,
    market: str,
    symbols: list[str],
    run_id: str,
    output_dir: Path,
    database: Path,
    alpaca_feed: str = "iex",
    as_of: datetime | None = None,
    intraday_adapter: MarketDataAdapter | None = None,
    daily_adapter: MarketDataAdapter | None = None,
) -> dict:
    if provider not in {"qmt", "alpaca"}:
        raise ValueError("provider must be qmt or alpaca")
    expected_market = "cn" if provider == "qmt" else "us"
    if market != expected_market:
        raise ValueError(f"provider {provider} requires market {expected_market}")
    db = _database_manager(database)
    radar = StockRadarTechnicalStateRadar(StockRadarTechnicalStateRepository(db))
    intraday = intraday_adapter or _intraday_adapter(provider, alpaca_feed=alpaca_feed)
    daily = daily_adapter or ExistingMarketDataAdapter(DataFetcherManager())
    runtime = StockRadarProviderRuntime(intraday, daily, radar=radar)
    return runtime.run(
        market=market,
        run_id=run_id,
        symbols=symbols,
        output_dir=output_dir,
        as_of=as_of or datetime.now(timezone.utc),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("qmt", "alpaca"), required=True)
    parser.add_argument("--market", choices=("cn", "us"), required=True)
    parser.add_argument("--symbol", action="append", dest="symbols", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/screening"))
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.getenv("DATABASE_PATH", "data/stock_analysis.db")),
    )
    parser.add_argument("--alpaca-feed", default="iex")
    args = parser.parse_args(argv)
    result = run(
        provider=args.provider,
        market=args.market,
        symbols=args.symbols,
        run_id=args.run_id,
        output_dir=args.output_dir,
        database=args.database,
        alpaca_feed=args.alpaca_feed,
    )
    runtime = result.get("runtime") or {}
    print(
        "Stock Radar technical-state run complete: "
        f"requested={runtime.get('requested_count', 0)}, "
        f"evaluated={runtime.get('evaluated_count', 0)}, "
        f"failed={runtime.get('failed_count', 0)}, "
        f"warnings={runtime.get('warning_count', 0)}"
    )
    return 0 if runtime.get("evaluated_count", 0) else 2


if __name__ == "__main__":
    raise SystemExit(main())

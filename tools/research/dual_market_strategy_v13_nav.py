"""Research-only independent NAV reconstruction for dual-market V1.0/V1.1."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from tools.research.dual_market_strategy_v08 import COSTS, DEFAULT_END, fetch_history, price_frame
from tools.research.dual_market_strategy_v08 import recovery_days
from tools.research.dual_market_strategy_v10 import ALL_SYMBOLS as V10_SYMBOLS
from tools.research.dual_market_strategy_v10 import WEIGHTS as WEIGHTS_V10, state_path as state_path_v10
from tools.research.dual_market_strategy_v11 import ALL_SYMBOLS as V11_SYMBOLS, CANDIDATES
from tools.research.dual_market_strategy_v11 import WEIGHTS as WEIGHTS_V11
from tools.research.dual_market_strategy_v11 import nav_ledger_from_states, state_path


def reconstruct(raw: dict[str, pd.DataFrame], output_dir: Path, end: str) -> dict[str, str]:
    symbols = sorted(set(V10_SYMBOLS) | set(V11_SYMBOLS))
    prices = price_frame(raw, symbols)
    output_dir.mkdir(parents=True, exist_ok=True)
    ledgers, reconciliations = [], []
    for fee, slip, label in COSTS:
        strategies = [("V1.0_STATE_SWITCH", state_path_v10(prices), WEIGHTS_V10)]
        strategies.extend((name, state_path(prices, cfg), WEIGHTS_V11)
                          for name, cfg in CANDIDATES.items())
        for name, states, weights in strategies:
            ledger = nav_ledger_from_states(prices, states, weights, fee, slip)
            ledger["strategy"], ledger["cost_scenario"] = name, label
            ledgers.append(ledger.reset_index())
            reconciliations.append({
                "strategy": name, "cost_scenario": label,
                "rows": len(ledger), "start": str(ledger.index.min().date()),
                "end": str(ledger.index.max().date()),
                "final_nav": float(ledger["nav"].iloc[-1]),
                "cumulative_return": float(ledger["nav"].iloc[-1] - 1.0),
                "max_drawdown": float((ledger["nav"] / ledger["nav"].cummax() - 1.0).min()),
                "cagr": float(ledger["nav"].iloc[-1] ** (252.0 / len(ledger)) - 1.0),
                "recovery_days": recovery_days(ledger["net_return"]),
                "total_turnover": float(ledger["turnover"].sum()),
                "total_transaction_cost": float(ledger["transaction_cost"].sum()),
                "nav_return_max_abs_difference": float(
                    (ledger["net_return"] - ledger["nav"].pct_change().fillna(0.0)).abs().max()),
            })
    ledger_path = output_dir / "stock_razor_dual_market_strategy_v13_daily_nav_ledger.csv"
    recon_path = output_dir / "stock_razor_dual_market_strategy_v13_nav_reconciliation.csv"
    metadata_path = output_dir / "stock_razor_dual_market_strategy_v13_nav_metadata.json"
    pd.concat(ledgers, ignore_index=True).to_csv(ledger_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(reconciliations).to_csv(recon_path, index=False, encoding="utf-8-sig")
    metadata = {
        "source": "local OpenD only", "endpoint": "127.0.0.1:11111",
        "query": {"ktype": "K_DAY", "session": "RTH", "autype": "QFQ", "end": end},
        "accounting": "daily prices, target weights, drifted end weights, cash residual, turnover and transaction costs",
        "signal_timing": "closed_prior_rows_only_next_day_effective",
        "calendar": "price index only; no calendar-day synthesis",
        "cash": "no uninvested cash; US.SHV is a cash-like defensive proxy, not verified cash",
        "qfq_dividend_semantics": "UNKNOWN", "provider_finality": "UNKNOWN",
        "timezone_exchange_calendar": "UNKNOWN", "oos_status": "NOT_VERIFIED",
        "radar_admission": "BLOCKED", "paper_auto_ready": "NO", "trade_execution": "NO",
        "sha256": {ledger_path.name: hashlib.sha256(ledger_path.read_bytes()).hexdigest(),
                   recon_path.name: hashlib.sha256(recon_path.read_bytes()).hexdigest()},
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = output_dir / "stock_razor_dual_market_strategy_v13_nav_report.md"
    report_path.write_text("\n".join([
        "# STOCK RAZOR Dual-Market Strategy V1.3 独立 NAV 重建", "",
        f"真实回放区间：{prices.index.min().date()}—{prices.index.max().date()}；",
        "仅使用本机 OpenD K_DAY/RTH/QFQ，价格索引是唯一交易日索引。",
        "状态未改变时持有漂移后的实际权重，仅在首日或状态切换时再平衡；US.SHV 是现金类代理，不冒充现金。", "",
        "逐日 ledger 已包含价格、目标权重、漂移后权重、现金残差、换手、交易成本、净收益和 NAV。",
        "QFQ 总回报语义、provider finality、独立交易日历与 OOS 仍为 UNKNOWN/NOT_VERIFIED。", "",
    ]) + "\n", encoding="utf-8")
    return {"ledger": str(ledger_path), "reconciliation": str(recon_path),
            "metadata": str(metadata_path), "report": str(report_path)}


def main(output_dir: Path, end: str = DEFAULT_END) -> None:
    from futu import OpenQuoteContext
    ctx = OpenQuoteContext(host="127.0.0.1", port=11111)
    raw = {}
    try:
        for symbol in sorted(set(V10_SYMBOLS) | set(V11_SYMBOLS)):
            frame, status = fetch_history(ctx, symbol, end)
            if frame is None:
                raise RuntimeError(f"{symbol}: {status}")
            raw[symbol] = frame
    finally:
        ctx.close()
    print(json.dumps(reconstruct(raw, output_dir, end), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    main(args.output_dir, args.end)

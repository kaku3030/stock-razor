# Round25 current six-strategy backtest status

Date: 2026-10-20 (Asia/Tokyo)  
Status: **PARTIAL — S2 BLOCKED**. This report combines the existing Round24 replay artifacts with the Round25 OpenD 1m audit. S1 and S3–S6 results are carried forward unchanged; they were not rerun on the new 1m files.

## 10 bps per side: full period and fixed OOS

Initial equity was $100,000 per isolated strategy. MDD is shown in dollars and as a fraction of peak equity. The OOS window is 2024-01-01 through 2026-10-16; the full window is 2019-01-01 through 2026-10-16.

| Arm | Full net P&L | PF | MDD | Trades | Win rate | OOS net P&L | PF | MDD | Trades | Win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S1 | $-56,528.40 | 0.75 | $59,447.86 (57.76%) | 1529 | 37.48% | $-18,714.47 | 0.85 | $26,612.97 (24.66%) | 620 | 40.00% |
| S2 | BLOCKED | — | — | — | — | BLOCKED | — | — | — | — |
| S3 | $4,730.42 | 1.88 | $2,049.05 (1.93%) | 40 | 50.00% | $1,430.20 | 1.42 | $1,984.48 (1.93%) | 22 | 40.91% |
| S4 | $1,921.20 | 1.85 | $1,158.26 (1.13%) | 17 | 52.94% | $683.24 | 1.85 | $648.92 (0.64%) | 6 | 50.00% |
| S5 | $32,938.66 | 1.82 | $4,302.87 (3.37%) | 258 | 52.33% | $7,698.82 | 1.50 | $3,485.92 (3.28%) | 103 | 45.63% |
| S6 | $26,270.96 | 1.17 | $9,513.36 (7.96%) | 796 | 43.72% | $5,966.06 | 1.11 | $5,977.46 (5.41%) | 301 | 41.86% |

## Net P&L cost stress

Each cost is per side. These are the existing Round24 outputs, not reruns on the new 1m capture.

| Arm | Full 5 bps | Full 10 bps | Full 20 bps | OOS 5 bps | OOS 10 bps | OOS 20 bps |
|---|---:|---:|---:|---:|---:|---:|
| S1 | $-37,516.08 | $-56,528.40 | $-79,019.01 | $-6,254.51 | $-18,714.47 | $-38,899.79 |
| S2 | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED |
| S3 | $4,985.14 | $4,730.42 | $4,222.77 | $1,573.69 | $1,430.20 | $1,143.80 |
| S4 | $2,150.12 | $1,921.20 | $1,464.75 | $732.88 | $683.24 | $584.02 |
| S5 | $34,782.82 | $32,938.66 | $29,324.90 | $8,310.56 | $7,698.82 | $6,485.42 |
| S6 | $41,090.01 | $26,270.96 | $1,125.84 | $10,661.38 | $5,966.06 | $-2,840.23 |

## Buy-and-hold benchmark

Equal-dollar across the same six symbols.

| Window | Return | MDD | MDD % | Final equity |
|---|---:|---:|---:|---:|
| Full 2019–2026 | 2068.06% | $530,025.22 | 58.63% | $2,168,059.37 |
| Train 2019–2023 | 628.12% | $448,189.23 | 58.63% | $728,122.39 |
| OOS 2024–2026 | 214.92% | $113,239.12 | 38.36% | $314,917.28 |

## Current S2 gate

The Round16 contract only states “Radar D1+1H+15m+5m+1m; closed-bar confirmations only.” The inspected Round11 code lists a D protocol but does not implement its signal generation or trade replay. Round24 builds S1 and S3–S6 only. No frozen S2 trigger/entry/exit/risk contract or Round16–23 S2 ledger was found.

OpenD now has 1m history for all six symbols, but the audited COHR file contains one unrepaired invalid OHLC bar at 2025-02-11 09:31 ET. Therefore a six-symbol S2 result remains blocked pending a deterministic frozen rule and resolution or explicit treatment of that source anomaly. No proxy rule was substituted.

## Reproducibility and limits

- High-timeframe Round24 input: 24 local QFQ/RTH files (D1/1H/15m/5m) for AAPL, AMD, COHR, NVDA, QQQ and TSLA; the raw files are not in this repository.
- Round24 re-used Round13/14 signal ledgers with matching source hashes; S3/S4 use SRVP entry-confirmation filters.
- Source timezone, exchange calendar, bar finality/closure and redistribution rights remain unknown; six symbols do not establish a broader-universe edge.
- The 1m audit and S2 provenance: [data-quality audit](round25_opend_1m_data_quality_audit.md), [S2 rule provenance](round25_s2_rule_provenance.md).
- Existing Round24 artifacts: [original report](https://github.com/kaku3030/stock-razor/blob/research/round24-six-strategy-backtest-20261020/outputs/round24_six_strategy_backtest_20261020/round24_report.md), [metrics](https://github.com/kaku3030/stock-razor/blob/research/round24-six-strategy-backtest-20261020/outputs/round24_six_strategy_backtest_20261020/round24_strategy_metrics.csv), [full cost stress](https://github.com/kaku3030/stock-razor/blob/research/round24-six-strategy-backtest-20261020/outputs/round24_six_strategy_backtest_20261020/round24_cost_stress_full.csv), [OOS metrics](https://github.com/kaku3030/stock-razor/blob/research/round24-six-strategy-backtest-20261020/outputs/round24_six_strategy_backtest_20261020/round24_oos_metrics.csv), [trade ledger](https://github.com/kaku3030/stock-razor/blob/research/round24-six-strategy-backtest-20261020/outputs/round24_six_strategy_backtest_20261020/round24_trade_ledger.csv), [daily equity](https://github.com/kaku3030/stock-razor/blob/research/round24-six-strategy-backtest-20261020/outputs/round24_six_strategy_backtest_20261020/round24_daily_equity_10bps.csv), [source manifest](https://github.com/kaku3030/stock-razor/blob/research/round24-six-strategy-backtest-20261020/outputs/round24_six_strategy_backtest_20261020/round24_source_manifest.json).

Trading and promotion remain disabled: `RADAR_ADMISSION=BLOCKED`, `PAPER_AUTO_READY=NO`, `LIVE_TRADE=NO`, `TRADE_EXECUTION=NO`.

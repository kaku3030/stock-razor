# Round24: unified six-strategy historical replay

**Status: PARTIAL_DATA_BLOCKED.** S1 and S3–S6 were rerun on the same frozen six-symbol Futu/OpenD capture. S2 is blocked because genuine historical 1m bars are absent; a Round22 test fixture was excluded.

The Round13 signal ledger and Round14 SRVP confirmation ledger both match all 24 raw capture SHA256 values. S3/S4 use SRVP as an entry-confirmation filter. At each 5/10/20 bps per-side scenario, the same signals are replayed with scenario-specific sizing and costs under the cash constraint.

## 10 bps/side comparison

| Arm | Full net P&L | Full PF | Full MDD | Full trades | Full win rate | OOS net P&L | OOS PF | OOS MDD | OOS trades | OOS win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S1 | -56,528.40 | 0.75 | 59,447.86 | 1529 | 37.5% | -18,714.47 | 0.85 | 26,612.97 | 620 | 40.0% |
| S2 | BLOCKED: no genuine historical 1m input | — | — | — | — | — | — | — | — | — |
| S3 | 4,730.42 | 1.88 | 2,049.05 | 40 | 50.0% | 1,430.20 | 1.42 | 1,984.48 | 22 | 40.9% |
| S4 | 1,921.20 | 1.85 | 1,158.26 | 17 | 52.9% | 683.24 | 1.85 | 648.92 | 6 | 50.0% |
| S5 | 32,938.66 | 1.82 | 4,302.87 | 258 | 52.3% | 7,698.82 | 1.50 | 3,485.92 | 103 | 45.6% |
| S6 | 26,270.96 | 1.17 | 9,513.36 | 796 | 43.7% | 5,966.06 | 1.11 | 5,977.46 | 301 | 41.9% |

## Equal-weight buy-and-hold benchmark

| Window | Return | Max drawdown | Max drawdown % | Final equity |
|---|---:|---:|---:|---:|
| Full 2019–2026 | 2068.06% | 530,025.22 | 58.63% | 2,168,059.37 |
| OOS 2024–2026 | 214.92% | 113,239.12 | 38.36% | 314,917.28 |

## Cost stress

See round24_cost_stress_full.csv for 5/10/20 bps per-side net P&L, PF, drawdown, trade count and win rate; each cost reruns cash-constrained sizing. round24_oos_metrics.csv contains the same measures for the fixed OOS window.

Input: 24 hashed files across 6 symbols, D1/1H/15m/5m, 2019-01-02 00:00:00 through 2026-10-16. Initial equity: $100,000 per isolated strategy.

Buy-and-hold is equal-dollar, equally weighted across the same six symbols. OOS is 2024-01-01 through 2026-10-16; 2019–2023 is the reference/training period. No parameters were fitted on OOS.

## Data limits

- Source metadata identifies Futu/OpenD, qfq and requested RTH. Provider timezone, exchange calendar, bar closure, provider finality and redistribution rights remain UNKNOWN.
- Six symbols do not support broader-universe conclusions. No synthetic, interpolated or test-fixture 1m bars were used.
- Accounting residual 1.46e-11; cash nonnegative=True; drawdown nonnegative=True.
- Radar, paper, deployment and trading gates remain disabled.

Runtime: 250.12s.

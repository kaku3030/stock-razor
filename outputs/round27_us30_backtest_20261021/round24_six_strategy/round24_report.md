# Round24: unified six-strategy historical replay

**Status: PARTIAL_DATA_BLOCKED.** S1 and S3–S6 were rerun on the same frozen six-symbol Futu/OpenD capture. S2 is blocked because genuine historical 1m bars are absent; a Round22 test fixture was excluded.

The Round13 signal ledger and Round14 SRVP confirmation ledger both match all 24 raw capture SHA256 values. S3/S4 use SRVP as an entry-confirmation filter. At each 5/10/20 bps per-side scenario, the same signals are replayed with scenario-specific sizing and costs under the cash constraint.

## 10 bps/side comparison

| Arm | Full net P&L | Full PF | Full MDD | Full trades | Full win rate | OOS net P&L | OOS PF | OOS MDD | OOS trades | OOS win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| S1 | -75,202.46 | 0.74 | 78,816.43 | 2637 | 37.3% | -32,313.97 | 0.82 | 37,628.07 | 999 | 38.6% |
| S2 | BLOCKED: no genuine historical 1m input | — | — | — | — | — | — | — | — | — |
| S3 | 5,227.56 | 1.23 | 3,580.10 | 146 | 43.2% | 2,654.69 | 1.27 | 3,492.57 | 63 | 41.3% |
| S4 | 2,597.08 | 1.19 | 2,727.42 | 84 | 42.9% | 1,573.10 | 1.35 | 1,451.80 | 29 | 44.8% |
| S5 | 19,374.32 | 1.36 | 7,507.95 | 329 | 45.9% | 3,915.66 | 1.18 | 6,295.35 | 140 | 42.9% |
| S6 | 1,197.21 | 1.01 | 11,786.69 | 1294 | 40.3% | 5,128.82 | 1.06 | 12,244.61 | 480 | 41.0% |

## Equal-weight buy-and-hold benchmark

| Window | Return | Max drawdown | Max drawdown % | Final equity |
|---|---:|---:|---:|---:|
| Full 2019–2026 | 936.51% | 234,916.44 | 40.57% | 1,036,505.65 |
| OOS 2024–2026 | 159.40% | 71,184.81 | 31.52% | 259,403.84 |

## Cost stress

See round24_cost_stress_full.csv for 5/10/20 bps per-side net P&L, PF, drawdown, trade count and win rate; each cost reruns cash-constrained sizing. round24_oos_metrics.csv contains the same measures for the fixed OOS window.

Input: 120 hashed files across 30 symbols, D1/1H/15m/5m, 2019-01-02 00:00:00 through 2026-10-16. Initial equity: $100,000 per isolated strategy.

Buy-and-hold is equal-dollar, equally weighted across the same six symbols. OOS is 2024-01-01 through 2026-10-16; 2019–2023 is the reference/training period. No parameters were fitted on OOS.

## Data limits

- Source metadata identifies Futu/OpenD, qfq and requested RTH. Provider timezone, exchange calendar, bar closure, provider finality and redistribution rights remain UNKNOWN.
- Six symbols do not support broader-universe conclusions. No synthetic, interpolated or test-fixture 1m bars were used.
- Accounting residual 1.46e-11; cash nonnegative=True; drawdown nonnegative=True.
- Radar, paper, deployment and trading gates remain disabled.

Runtime: 573.40s.

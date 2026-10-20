# Round16: six-strategy × market-regime research contract

Status: **RESEARCH_ONLY / DATA_BLOCKED**. This is a preregistered experiment specification, **not** a backtest result. Never enable RADAR_ADMISSION, PAPER_AUTO_READY, LIVE_TRADE or TRADE_EXECUTION.

## Research arms (freeze definitions before results)

- S1: SRVP standalone; preserve original SRVP trigger and execution rules.
- S2: Radar D1+1H+15m+5m+1m; closed-bar confirmations only.
- S3: SRVP + Radar D1+1H.
- S4: SRVP + Radar D1+1H+15m.
- S5: Radar D1+1H.
- S6: Radar D1+1H+15m.

S3 and S4 must specify whether SRVP is a filter, score or sizing overlay **before** running OOS; run these roles as separate named sub-arms, not interchangeable implementations. Existing Round13 II/III and Round14 IV/V are historical reference points only until ledger parity is demonstrated. Do not attribute S5/S6 differences exclusively to 15m unless parent signals are held constant.

## Universe and data gate

Stage A: 30–60 assets; Stage B: 100; Stage C: 150–200. Maintain separate US and CN cohorts, industry stratification, delisted/inactive symbols and point-in-time universe membership. US bars only via authorized OpenD; CN bars only via authorized TickFlow. Never upload raw licensed captures to a public repository. Verify provider rights, symbol adjustment factors, time zones, session boundaries, 1m/5m/15m/1H/D1 coverage, timestamp ordering, OHLC finiteness, missingness, closed-bar finality and SHA256 before research. A six-symbol sample cannot substantiate 30–60 symbol claims. No proxy or synthetic bars may be reported as market backtests.

## Market regime labels (causal, timestamped)

Calculate labels using information **available at the decision timestamp**, separately for benchmark market and individual asset:
- TREND_UP_STRONG / TREND_UP_WEAK
- TREND_DOWN_STRONG / TREND_DOWN_WEAK
- RANGE_WIDE / RANGE_NARROW
- TRANSITION
- UNKNOWN for insufficient or stale data.

Pre-register trend-strength, directional and volatility thresholds on training periods only. Use prior closed D1/1H bars and a fixed volatility/ADX or slope specification; no future turning points or retrospectively assigned labels. Report regime transitions and confusion/sensitivity to threshold perturbations. Downtrend cells with insufficient trade counts remain UNDERPOWERED.

## Evaluation

Freeze universe, calendar, baseline equity, transaction costs, corporate actions, market-specific execution rules, no-lookahead fills, stop semantics, risk-per-trade, concurrency and exposure caps. Report annual and fixed OOS results, rolling walk-forward, 2020/2022 stress, regime × arm × market matrix, n, PF, net PnL, expectancy, win rate, exposure-adjusted return, drawdown, time in market and costs at 5/10/20 bps per side. Use paired signal-level ablation and exposure-matched controls. Confidence intervals must account for symbol/time clustering and multiple comparisons. Run independent ledger-to-equity reconciliation and identify the **first divergent trade** in Round14 vs Round15 Protocol III before accepting cross-round comparisons.

## Promotion and audit

Artifacts: immutable run config, code/data SHA256 manifest, symbol coverage matrix, signal and fill ledgers, equity curves, regime assignments, OOS/walk-forward summaries, tests, environment, runtime, and comparison report. Any missing raw inputs, CI evidence or unresolved ledger parity => NOT_VERIFIED/BLOCKED. No PR merge, production deploy, paid provider calls, paper-auto promotion or live orders.

# Strong Pullback Strategy V0.1

Research-only specification. `TRADE_EXECUTION=NO`; this document does not change `RADAR_ADMISSION` or `SOURCE_ARBITER_ADMISSION`.

## Mechanical rules

All inputs must be timezone-aware, provider-lineaged, PIT-verified, survivorship-controlled, and closed. Weekly/daily context and 60m structure are evaluated before a 15m trigger. 5m is not used in V0.1.

- **A — first/second shallow pullback:** daily close is above its last-20-bar median and 60m close is above its value four bars earlier. On 15m, the prior three bars have lows no lower than 1.5% below the preceding ten-bar support and median volume no greater than 80% of the prior-ten-bar median. Trigger: the closed bar closes above the last pullback high and volume is at least the baseline median. Invalidation: a closed low below `support * 0.985`. The first qualifying pullback is A1; the next is A2. They are reported separately.
- **B — breakout, acceptance, relaunch:** the closed 15m bar breaks the prior 20-bar high on volume at least 1.5x baseline. At least one of the next three closed bars accepts above 99% of the breakout level and closes within 0.5% below it or above it. Trigger: a later closed bar closes above the accepted breakout level. Invalidation: closed low below `breakout * 0.99`.
- **C — contraction breakout:** the prior five closed 15m bars have a range no greater than 80% of the prior-ten-bar median and median volume no greater than 70% of baseline. Trigger: a closed bar breaks the five-bar high on volume at least 1.2x baseline. Invalidation: closed low below the contraction base low.

## Evaluation contract

The backtest enters at the next bar open, applies explicit commission and slippage on entry/exit, checks the stop before the horizon close, and reports expected value, win rate, mean winning/losing R, R distribution, maximum drawdown, trade count, and scenario stability. A result with no complete trades is `INSUFFICIENT`, not a zero-return success.

The code does not fetch market data. A-share qualification requires explicit `provider=tickflow`; US qualification requires explicit `provider=alpaca`, but Alpaca feed scope and consolidated-volume semantics remain a separate evidence item. No current TickFlow or qualified US capture is asserted by fixture tests. Walk-forward/OOS/Shadow/Paper admission remains pending a governed dataset capsule, split manifest, and real provenance evidence.


## P0/P1 audit patch: execution and timing safeguards

- Per-candidate daily and 60m trend evaluations use only completed bar-END
  timestamps at or before the historical 15m trigger. A later trend bar cannot
  retroactively create a past trade signal. Bar ordering/uniqueness is guarded.
- Explicit settlement and market time zone are **required** for simulation.
  A-share equity ETFs generally require T+1 sell eligibility; do not assume
  every ETF is T+1 (or T+0). An unsellable same-day stop remains open, and a
  next-session gap through stop executes at the executable opening price
  with adverse slippage, not the hypothetical stop.
- Single-position simulation skips overlapping candidate trades. Reported
  drawdown includes sequential bar-close marks while held (not unobservable
  intrabar equity extrema). An invalid stop distance fails closed.
- A1/A2/A3+ are ordinal qualifying pullbacks within the current continuous
  detected trend segment. The first is A1, second A2; later signals are not
  mislabeled A2. These are research labels only.
- The PASS result from a synthetic test indicates mathematical **contract
  execution** only. It does not attest vendor provenance, data quality,
  profitability, realistic broker execution, or out-of-sample performance.
  Real OOS/Shadow/Paper are still BLOCKED/NOT_RUN.

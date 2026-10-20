# Round27 US30 research universe candidate

Date: 2026-10-20 (Asia/Tokyo)  
Branch: `research/round27-us30-universe-candidate-20261020`  
Status: `CANDIDATE_PENDING_PIT_AND_DATA_GATE`  
Purpose: prepare the next 30-symbol US cohort before computing any 30-symbol strategy returns.

## Candidate symbols

The first 12 retain the existing US list in `config/research_universe_v0_1.json`. The other 18 extend coverage across technology, consumer, finance, energy, healthcare and industrials. No 30-symbol return results were consulted when adding them.

| Group | Symbols |
|---|---|
| Existing US cohort (12) | SPY, QQQ, NVDA, AMD, AAPL, TSLA, ANET, MRVL, QCOM, TSM, COHR, VRT |
| Proposed additions (18) | MSFT, AMZN, GOOGL, META, AVGO, MU, INTC, ORCL, CRM, JPM, XOM, CVX, LLY, UNH, CAT, BA, HD, COST |
| Candidate total | 30 unique symbols |

This is a fixed-symbol research candidate, not a point-in-time constituent universe and not an approved strategy cohort. It is not eligible for performance claims until the data and membership gates below pass.

## Required gates before capture is accepted

1. Establish a defensible point-in-time selection rule and membership evidence for the experiment dates. Add inactive/delisted names where required. If this cannot be done, label the study explicitly as a fixed-survivor cohort and do not generalize its returns to a 30-stock universe.
2. Keep the US cohort separate from CN assets. Use only authorized local OpenD bars for US symbols; do not substitute a cloud cache, Alpaca, yfinance, proxy or synthetic data.
3. Before backtest, freeze the symbol list, sector labels, adjustment/session settings, date range, costs, execution and strategy definitions. No selection based on observed 30-symbol strategy returns.
4. Capture and audit D1, 1H, 15m, 5m and 1m OHLCV for every symbol over the same requested 2019-01-01 through 2026-10-16 interval, or document each symbol's genuine listing/data start. Preserve raw captures locally; commit only manifests, hashes, audit results, ledgers and reports.
5. Verify provider rights, timestamps/time zone, session calendar and finality, OHLC validity, ordering, duplicates, missing bars, corporate-action adjustment and SHA256. Any unresolved gate keeps the run `BLOCKED`.
6. Rebuild all six strategy arms and the equal-weight buy-and-hold benchmark on this same 30-symbol cohort. Report per-symbol coverage, 5/10/20 bps per-side costs, train/OOS results and trade-level ledgers. Do not reuse six-symbol portfolio metrics as 30-symbol results.

## Current execution constraint

The Windows OpenD capture is local to the user's machine. The Remote Desktop Commander monthly quota is exhausted, and this workspace has no mounted copy of the ignored local captures. Therefore this candidate file does not claim data capture or a 30-symbol backtest has run. Raw historical bars remain required before computation.


## Backtest-engine compatibility finding

Inspection of `tools/research/round24_six_strategy_backtest.py` shows the current runner is bound to the Round13 symbol tuple. It also refuses cached Round13/Round14 signal ledgers unless their SHA256 map exactly matches the capture manifest. Those caches describe the original six-symbol cohort. Adding 24 CSV sets and rerunning Round24 would therefore either fail the hash gate or reuse the wrong signal set.

Round27 must explicitly load all 30 configured symbols with fail-closed coverage, rebuild Round13 signals and Round14 SRVP confirmation flags from the 30-symbol captures, and then replay all arms and the equal-weight benchmark on that same cohort. The existing Round13 driver also selects only its built-in symbol list and silently marks others unavailable; its driver needs an explicit-universe entry point before a complete 30-symbol run. The underlying signal and accounting functions can be reused, but the six-symbol cache cannot.

This code-path change is independent of Windows access. Raw OpenD captures for the additional symbols are still required before producing return metrics.

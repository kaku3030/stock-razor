# Round28 100-name candidate universe

**Composition:** 70 U.S. equities + 30 A-share equities. Research candidates only; no strategy promotion.

## Selection method

- **U.S. (70):** retain the 28 stock names from Round27 and remove its two ETF benchmarks (SPY, QQQ); add 42 names present in the Nasdaq-100 candidate snapshot dated 2026-10-15. The 28-name overlap reuses Round27 captures. Round28 added captures now cover 32/42 names; 10 added names remain without data. Current effective coverage is 60/70 U.S. names.
- **A-shares (30):** propose large/liquid CSI300-oriented names across sectors. The official CSI300 factsheet dated 2026-03-31 is used only as a top-holdings reference; full constituent membership and historical point-in-time membership for this exact 30-name list remain unverified.
- **Sample window:** 2019-01-01 to 2026-10-16; D1, 1H, 15m, 5m, and 1m inputs.
- **Accounting:** keep USD and CNY portfolios separate. Do not pool their P&L or drawdowns. Apply the same 5/10/20 bps sensitivity grid only after market-specific commissions, taxes, lot sizes, T+1, price limits, corporate actions, and fill rules are specified.
- **S2:** candidate only; the official frozen rule is still unavailable.

## U.S. candidates

The first 28 are the Round27 stock cohort. The remaining 42 are drawn from the Nasdaq-100 candidate snapshot.

`AAPL, AMD, NVDA, TSLA, ANET, MRVL, QCOM, TSM, COHR, VRT, MSFT, AMZN, GOOGL, META, AVGO, MU, INTC, ORCL, CRM, JPM, XOM, CVX, LLY, UNH, CAT, BA, HD, COST`

`ADBE, ADI, ADP, ADSK, AMAT, AMGN, APP, ASML, AXON, BKNG, CEG, CMCSA, CRWD, CSCO, CTAS, DASH, DDOG, GEHC, GILD, INTU, ISRG, KLAC, LRCX, MELI, MPWR, NFLX, NXPI, PANW, PDD, PEP, PLTR, REGN, ROP, SBUX, SHOP, SNPS, TMUS, TXN, VRTX, WMT, WDC, ABNB`

## A-share candidates

`600519.SH, 300750.SZ, 300308.SZ, 601318.SH, 601899.SH, 600036.SH, 300502.SZ, 000333.SZ, 600900.SH, 601166.SH, 002594.SZ, 300760.SZ, 600276.SH, 601012.SH, 002475.SZ, 600030.SH, 601888.SH, 000858.SZ, 600809.SH, 002415.SZ, 601398.SH, 300015.SZ, 603259.SH, 600031.SH, 600104.SH, 601728.SH, 601668.SH, 601225.SH, 600309.SH, 601919.SH`

## Data gate observed 2026-10-21

- 300/500 required market/timeframe files exist: 60/70 U.S. symbols × 5 frames; ten U.S. symbols remain missing.
- Local OpenD history quota is exhausted: 100 used, 0 remaining. The ten missing U.S. symbols exceed the remaining quota.
- 0/150 A-share files exist. The local OpenD A-share request was denied by account entitlement. No local TickFlow historical cache was found in the inspected paths; its paid historical route was not called.
- A 60-name U.S.-only exploratory replay is complete. It excludes the ten missing U.S. names and all 30 A-shares, and does not satisfy the 100-name objective. See ../round28_us60_us_only_exploratory_20261021/round28_us60_backtest_report.md.
- That subset audit found 467 invalid OHLCV rows across 23 symbols and 420 symbol-session pairs. Affected sessions were removed consistently across all frames and arms. S2 remains an unvalidated candidate; its official rule is unavailable.
- Point-in-time membership, provider finality, timestamp semantics, and independent data-quality signoff remain unresolved. The full 100-name gate stays BLOCKED.

## References

- Nasdaq-100 weighting page / candidate snapshot: https://indexes.nasdaqomx.com/Index/Weighting/NDX
- Official CSI300 factsheet (2026-03-31): https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/en/000300factsheeten.pdf
- Futu OpenAPI history quota: https://openapi.futunn.com/futu-api-doc/en/quote/get-history-kl-quota.html
- Detailed per-market file coverage: `round28_data_gate_status.json`

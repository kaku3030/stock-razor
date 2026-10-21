# Round28 100-name candidate universe

**Composition:** 70 U.S. equities + 30 A-share equities. Research candidates only; no strategy promotion.

## Selection method

- **U.S. (70):** retain the 28 stock names from Round27 and remove its two ETF benchmarks (SPY, QQQ); add 42 names present in the Nasdaq-100 candidate snapshot dated 2026-10-15. The 28-name overlap reuses Round27's local Futu/OpenD captures. The added 42 names do not yet have Round28 capture files.
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

- 140/500 required market/timeframe files exist: 28 U.S. symbols × 5 frames.
- 42 U.S. symbols × 5 frames are missing. Local OpenD history quota reports 72 used and 28 remaining; this is 14 short of the missing U.S. symbols alone.
- 30 A-share symbols × 5 frames are missing. No local TickFlow historical capture/cache was found in the inspected capture/cache locations. TickFlow's history batch path is explicitly paid and gated; no request was made.
- No Round28 strategy backtest, cost stress test, or out-of-sample run is claimed. Round27's U.S. 30-stock results are not substituted for this cohort.

## References

- Nasdaq-100 weighting page / candidate snapshot: https://indexes.nasdaqomx.com/Index/Weighting/NDX
- Official CSI300 factsheet (2026-03-31): https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/en/000300factsheeten.pdf
- Futu OpenAPI history quota: https://openapi.futunn.com/futu-api-doc/en/quote/get-history-kl-quota.html
- Detailed per-market file coverage: `round28_data_gate_status.json`

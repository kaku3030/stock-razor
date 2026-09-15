# A-Share Intraday Provider Semantics Report

Date: 2026-09-10
Status: `PROVIDER-EVIDENCE / HARVEST REPORT`
Scope: CN A-share / ETF / index `15m` and `60m` provider capability and semantics relevant to Stock Razor intraday Data Health / Currentness.

This report is evidence/governance only. It authorizes **no production routing, provider priority, fallback, Currentness threshold, SHADOW/CORE promotion, strategy, AI, or trading behavior**.

## Executive conclusion

Multiple external providers clearly expose 15-minute and/or 60-minute China-market K-line data. That fact is now sufficiently evidenced for Efinance/Eastmoney, AKShare/Eastmoney, Tushare, TickFlow, TDX-family wrappers, and BaoStock historical stock bars.

However, **method availability is not Currentness authority**.

For every currently screened A-share provider, at least one critical semantic required by the candidate Currentness contract remains unresolved in the target scope, especially:

- whether the provider timestamp identifies bar start, bar end, or another provider-defined point;
- whether the newest row can be the currently forming bar;
- whether the same bar identity mutates while forming;
- how lunch break / opening / closing-call-auction boundaries are represented in 15m/60m aggregation;
- final-bar behavior at close;
- suspension / zero-trade interval behavior;
- exact publication delay and current-day completeness semantics.

Therefore:

> **No screened A-share intraday provider is `CURRENTNESS_ELIGIBLE` yet.**

The correct current state is to distinguish `SOURCE_VERIFIED interval capability` from `UNKNOWN/PARTIALLY_VERIFIED provider semantics`, and to keep production Currentness fail-closed until target-scope evidence is collected and independently reviewed.

## Evidence status vocabulary

- `SOURCE_VERIFIED`: official/provider-owned documentation or source establishes the fact.
- `VERIFIED_TESTED_SCOPE`: controlled observation establishes the fact only in the observed scope/version.
- `PARTIALLY_VERIFIED`: evidence narrows the claim but does not close the exact target semantic.
- `CORROBORATING_ONLY`: mature third-party implementation/observation suggests a behavior but is not provider-authoritative.
- `UNKNOWN`: no acceptable evidence closes the fact.

CI/test status is intentionally separate from provider evidence status.

## Provider truth matrix

| Provider / lineage | Instrument | 15m | 60m | Access mode evidenced | Entitlement | Timestamp field | Timestamp boundary | Forming bar | Units / adjustment evidence | Current Stock Razor intraday implementation | Currentness eligibility |
|---|---|---:|---:|---|---|---|---|---|---|---|---|
| Efinance / Eastmoney | A-share stock/ETF | SOURCE_VERIFIED | SOURCE_VERIFIED | historical/request K-line | no separate minute entitlement observed in library surface | date/time-like output | UNKNOWN | UNKNOWN | adjustment caller-selectable in upstream wrapper; exact intraday unit contract needs endpoint-specific verification | NOT_IMPLEMENTED; current fetcher uses `klt=101` daily | NOT ELIGIBLE |
| AKShare EM / Eastmoney | A-share stock | SOURCE_VERIFIED | SOURCE_VERIFIED | recent intraday history/request | no token required at wrapper level | `时间` | UNKNOWN | UNKNOWN | `adjust` supports none/qfq/hfq; docs explicitly describe 1m volume as lots; higher-period unit semantics must remain endpoint-scoped | NOT_IMPLEMENTED; current Stock Razor path is daily-oriented | NOT ELIGIBLE |
| AKShare EM / Eastmoney | ETF | SOURCE_VERIFIED | SOURCE_VERIFIED | recent intraday history/request | no token required at wrapper level | time/date field | UNKNOWN | UNKNOWN | none/qfq/hfq; exact minute unit semantics require endpoint-specific evidence | NOT_IMPLEMENTED; current Stock Razor path is daily-oriented | NOT ELIGIBLE |
| AKShare EM / Eastmoney | index | SOURCE_VERIFIED | SOURCE_VERIFIED | recent intraday history/request | no token required at wrapper level | `时间` | UNKNOWN | UNKNOWN | volume documented as lots, amount yuan | NOT IMPLEMENTED in admitted intraday capability | NOT ELIGIBLE |
| Tushare | A-share stock | SOURCE_VERIFIED | SOURCE_VERIFIED | realtime request + current-day replay | permission required; runtime entitlement must be verified | `time` | UNKNOWN | UNKNOWN | realtime docs: volume shares, amount yuan | NOT_IMPLEMENTED as admitted `kline.15m`/`kline.1h` contract | CURRENTNESS_CANDIDATE research lane only |
| Tushare | ETF | SOURCE_VERIFIED | SOURCE_VERIFIED | realtime + current-day replay + historical | permission required; runtime entitlement must be verified | `time` / `trade_time` | UNKNOWN | UNKNOWN | realtime docs: volume shares, amount yuan | NOT_IMPLEMENTED as admitted intraday contract | CURRENTNESS_CANDIDATE research lane only |
| Tushare | exchange index | SOURCE_VERIFIED | SOURCE_VERIFIED | historical minute request | separate minute permission | `trade_time` | UNKNOWN | UNKNOWN | endpoint-specific fields documented | NOT_IMPLEMENTED as admitted intraday contract | HISTORICAL/DIAGNOSTIC candidate |
| TickFlow full service | A-share | SOURCE_VERIFIED | SOURCE_VERIFIED | history/request + current-day intraday API | API key/full service required; free service explicitly excludes minute K-lines | `timestamp` / `trade_time` | UNKNOWN | UNKNOWN | adjustment options exist; endpoint-specific volume/amount contract to be pinned | NOT_IMPLEMENTED; current `TickFlowFetcher` main K-line path is daily | CURRENTNESS_CANDIDATE research lane only |
| PyTDX / TDX family | A-share stock | SOURCE/WRAPPER VERIFIED | SOURCE/WRAPPER VERIFIED | protocol request | no token in common TDX wrapper surface | `datetime`-like field | UNKNOWN | UNKNOWN | endpoint/protocol units need explicit contract audit | NOT_IMPLEMENTED; current Stock Razor `_fetch_raw_data()` hard-codes category `9` daily | NOT ELIGIBLE |
| BaoStock | A-share stock | SOURCE/ECOSYSTEM VERIFIED | SOURCE/ECOSYSTEM VERIFIED | historical request | no separate token entitlement in typical surface | `date`,`time` | UNKNOWN provider-authoritatively | UNKNOWN | minute fields include OHLC/volume/amount/adjustflag; exact unit semantics to pin from provider-owned docs | NOT_IMPLEMENTED; current Stock Razor path `frequency="d"` | HISTORICAL_ONLY candidate |

## 1. Efinance / Eastmoney

### Interval capability

Efinance's provider-owned GitHub examples/documentation expose `get_quote_history(..., klt=...)` with minute K-line frequencies. The upstream library uses Eastmoney historical K-line infrastructure. Current Stock Razor code, however, calls the Efinance history path with `klt=101`, i.e. daily K-line.

Evidence:
- upstream Efinance repository: `Micro-sheep/efinance`, including `README.md` and `efinance/stock/getter.py`;
- Stock Razor: `data_provider/efinance_fetcher.py` (`klt=101`).

Status:
- external 15m/60m capability: `SOURCE_VERIFIED`;
- Radar 15m/60m implementation: `NOT_IMPLEMENTED`;
- timestamp start/end: `UNKNOWN`;
- forming-bar semantics: `UNKNOWN`;
- Currentness: `NOT ELIGIBLE`.

### Lineage warning

Efinance and AKShare Eastmoney minute routes must not be counted as independent corroboration. They are separate adapters over the Eastmoney upstream family.

## 2. AKShare / Eastmoney minute routes

Official AKShare documentation defines:

- `stock_zh_a_hist_min_em`: `period` in `1,5,15,30,60`, recent A-share intraday history;
- `fund_etf_hist_min_em`: `period` in `1,5,15,30,60`, with no/qfq/hfq adjustment choices;
- `index_zh_a_hist_min_em`: `period` in `1,5,15,30,60` for recent index intraday data.

Official docs:
- https://akshare.akfamily.xyz/data/stock/stock.html
- https://akshare.akfamily.xyz/data/fund/fund_public.html
- https://akshare.akfamily.xyz/data/index/index.html

The stock/index docs expose time fields and sample rows, but do not define whether a 15m/60m timestamp is the start boundary, end boundary, or another provider convention. A sample time value is not itself a semantic contract.

Important unit discipline:
- AKShare's documented Eastmoney minute surfaces include endpoint-specific volume units; for example the index minute documentation explicitly says volume is in lots and amount in yuan.
- Unit semantics must remain bound to exact endpoint/instrument/period; they must not be generalized from one endpoint to all AKShare minute calls.

Status:
- external interval capability: `SOURCE_VERIFIED`;
- provider timestamp boundary: `UNKNOWN`;
- forming bar/current-row semantics: `UNKNOWN`;
- current Stock Razor intraday implementation: `NOT_IMPLEMENTED`;
- Currentness: `NOT ELIGIBLE`.

## 3. Tushare

Official Tushare documentation provides unusually clear capability surfaces:

### A-share stock
- `rt_min`: realtime A-share minute data including `15MIN` and `60MIN`;
- `rt_min_daily`: current-day cumulative minute replay from market open, including `15MIN` and `60MIN`.

Official docs:
- https://tushare.pro/document/2?doc_id=374
- https://tushare.pro/document/2?doc_id=457

The realtime stock docs explicitly document:
- `time`: trading time;
- `vol`: volume in shares;
- `amount`: turnover amount in yuan.

### ETF
- `etf_mins`: historical ETF 1/5/15/30/60-minute data;
- `rt_etf_min`: realtime ETF 1–60 minute data;
- `rt_etf_min_daily`: current-day cumulative ETF minute replay.

Official docs:
- https://tushare.pro/document/2?doc_id=387
- https://tushare.pro/document/2?doc_id=416
- https://tushare.pro/document/2?doc_id=470

### Index
- `idx_mins`: exchange-index historical 1/5/15/30/60-minute data, with separate permission.

Official doc:
- https://tushare.pro/document/2?doc_id=419

### What remains unresolved

The documentation says `time` / `trade_time` is trading time, but does not define the aggregation boundary semantic needed by Stock Razor:

- BAR_START vs BAR_END;
- whether the current forming 15m/60m bucket is returned;
- whether a same-key row mutates while forming;
- exact close/lunch aggregation behavior.

Therefore Tushare is a strong **controlled-evidence candidate**, not yet a Currentness authority.

Status:
- 15m/60m capability: `SOURCE_VERIFIED`;
- permission requirement: `SOURCE_VERIFIED`, runtime entitlement still per-account evidence;
- realtime/current-day replay existence: `SOURCE_VERIFIED`;
- stock realtime volume shares / amount yuan: `SOURCE_VERIFIED`;
- timestamp boundary: `UNKNOWN`;
- forming behavior: `UNKNOWN`;
- Currentness: `CURRENTNESS_CANDIDATE` research lane only.

## 4. TickFlow

### Evidence correction

An earlier Harvest note left authoritative TickFlow 15m/1h capability as UNKNOWN. Official TickFlow documentation closes that capability question.

Official docs state:
- A-share minute K-lines support `1m,5m,15m,30m,60m`;
- the free service provides historical daily K-lines only and **does not provide minute K-lines**;
- the full service requires an API key for realtime/minute capabilities;
- `/v1/klines` is the general K-line endpoint;
- `/v1/klines/intraday/batch` supports current-day intraday periods including `15m` and `60m`.

Official docs:
- https://docs.tickflow.org/zh-Hans
- https://docs.tickflow.org/zh-Hans/quickstart
- https://docs.tickflow.org/zh-hans/api-reference/k线数据/查询-k线数据
- https://docs.tickflow.org/zh-hans/api-reference/k线数据/批量查询当日分钟k线

Status:
- external 15m/60m capability: `SOURCE_VERIFIED`;
- full-service/API-key requirement: `SOURCE_VERIFIED`;
- free-service lack of minute bars: `SOURCE_VERIFIED`;
- current-day intraday endpoint: `SOURCE_VERIFIED`;
- timestamp field presence: `SOURCE_VERIFIED`;
- timestamp boundary: `UNKNOWN`;
- forming-bar/completion behavior: `UNKNOWN`;
- current Stock Razor intraday implementation: `NOT_IMPLEMENTED` (current `TickFlowFetcher` K-line path requests `period="1d"`);
- Currentness: `CURRENTNESS_CANDIDATE` research lane only.

## 5. TDX / PyTDX / mootdx

TDX-family protocol/wrapper documentation exposes K-line categories including:

- category `1`: 15-minute;
- category `3`: 1-hour;
- category `9`: daily.

Current Stock Razor `data_provider/pytdx_fetcher.py` explicitly comments these categories but calls `get_security_bars(category=9, ...)` in its unified history path.

This is an important capability distinction:

> protocol support does not mean Stock Razor currently implements the capability.

The original pytdx upstream has legacy/archive concerns, so protocol/wrapper behavior is useful Harvest evidence but not a reason to adopt a new runtime dependency blindly.

Unresolved for Currentness:
- timestamp boundary semantic;
- current/forming-row behavior;
- lunch/close aggregation;
- zero-trade/suspension behavior;
- hard blocking/failure containment for concrete chosen wrapper/server path.

Status:
- interval capability: `SOURCE/WRAPPER VERIFIED`;
- current Radar implementation: `NOT_IMPLEMENTED`;
- Currentness: `NOT ELIGIBLE`.

## 6. BaoStock

BaoStock provider ecosystem/source documentation exposes minute historical stock K-lines through `query_history_k_data_plus` with 15m/60m frequency support and minute fields including `date`, `time`, OHLC, volume, amount and adjustment information. Index minute support is not established as equivalent.

Current Stock Razor `data_provider/baostock_fetcher.py` calls the API with `frequency="d"`, so its current admitted path is daily only.

A mature third-party .NET implementation describes BaoStock's minute `Time` value as the bar end. Under Stock Razor evidence governance this is **CORROBORATING_ONLY**, because it is a third-party interpretation rather than provider-authoritative documentation or a controlled Stock Razor observation.

Therefore:
- historical 15m/60m availability: `SOURCE/ECOSYSTEM VERIFIED`;
- bar-end semantic: `UNKNOWN` provider-authoritatively;
- realtime/current-day Currentness contract: `UNKNOWN`;
- current Radar intraday implementation: `NOT_IMPLEMENTED`;
- recommended role: `HISTORICAL_ONLY` / backfill / cross-check candidate.

## 7. Exchange session authority

Provider semantics must be bounded by the exchange's actual trading session, but exchange hours still do not define provider candle construction.

Current Shanghai Stock Exchange trading rules define standard auction trading as:

- 09:15–09:25 opening call auction;
- 09:30–11:30 continuous auction;
- 13:00–14:57 continuous auction;
- 14:57–15:00 closing call auction.

Shenzhen Stock Exchange publishes the corresponding standard continuous-auction and closing-call-auction structure.

These rules can feed `TRADING_EXPECTATION` / session phase. They **cannot** by themselves prove:

- whether a provider's 15m bar stamped 09:45 represents 09:30–09:45 or 09:45–10:00;
- whether 60m is anchored to 09:30, 10:00, or a provider-defined sequence;
- how 11:30 and 13:00 are bucketed;
- whether 14:57–15:00 is included in a prior bucket, a final bucket, or represented by another convention;
- whether a suspended/no-trade interval should produce a bar.

Reference authorities:
- Shanghai Stock Exchange trading rules / market trading-time materials: https://www.sse.com.cn/
- Shenzhen Stock Exchange trading-time materials: https://www.szse.cn/

## Cross-provider independence implications

PR #40 lineage rules remain binding.

- `efinance` + `akshare_em` agreement = **one Eastmoney lineage**, not two independent confirmations.
- `akshare_qq` + realtime token `tencent` = one Tencent lineage where they resolve to the same upstream route.
- Tushare / TickFlow / TDX may provide independent corroboration only after each exact capability record independently satisfies its own semantic gates.
- unknown lineage cannot increase independence count.

No compensatory source-count scoring is authorized.

## Currentness authority decision

### Current state

| Provider lane | Currentness state | Why |
|---|---|---|
| Efinance/Eastmoney | NOT ELIGIBLE | Radar intraday path not implemented; timestamp/forming/session semantics unresolved |
| AKShare/Eastmoney | NOT ELIGIBLE | Radar intraday path not implemented; same Eastmoney lineage; critical semantics unresolved |
| Tushare | CURRENTNESS_CANDIDATE research only | realtime/current-day APIs exist, but critical timestamp/forming/session semantics unresolved and runtime entitlement must be proven |
| TickFlow | CURRENTNESS_CANDIDATE research only | full service/current-day minute API exists, but Radar path not implemented and critical semantics unresolved |
| TDX/PyTDX | NOT ELIGIBLE | protocol supports intervals, Radar path daily-only, semantics/failure containment unresolved |
| BaoStock | HISTORICAL_ONLY candidate | historical minute role; no sufficient realtime/currentness semantic contract |

### Governing rule

No provider can be promoted to `CURRENTNESS_ELIGIBLE` by:

- low latency alone;
- same trading date;
- a recent receive timestamp;
- a configured API key;
- provider reputation;
- agreement with another adapter over the same upstream;
- CI success;
- the existence of a 15m/60m method.

Critical provider semantics must be directly evidenced in the target provider/instrument/interval/access-mode scope.

## Recommended next evidence wave

Do **not** implement production routing yet. The next high-value slice is controlled provider observation using a shared evidence envelope.

For each candidate provider, capture at minimum:

1. provider / adapter / upstream lineage identity;
2. exact endpoint/method and interval;
3. instrument type and symbol;
4. entitlement/capability result;
5. provider timestamp value and raw row;
6. parent-observed UTC receive time + monotonic observation time;
7. repeated snapshots during one forming 15m/60m interval;
8. transition across a bucket boundary;
9. 11:30 lunch entry and 13:00 restart;
10. 14:57–15:00 close transition;
11. a no-trade/suspended control where feasible;
12. adjustment / volume / amount units;
13. timeout/failure outcome without treating timeout as semantic evidence.

The analyzer should keep competing hypotheses explicit:

- `BAR_START`
- `BAR_END`
- `PROVIDER_DEFINED_OTHER`
- `UNKNOWN`

It must never auto-promote a hypothesis merely because timestamps align with a convenient clock grid.

## Harvest disposition

- Efinance/Eastmoney: `ADAPT / PROVIDER-EVIDENCE REQUIRED`.
- AKShare/Eastmoney: `ADAPT / TEST-REUSE / PROVIDER-EVIDENCE REQUIRED`; do not count as independent from Efinance.
- Tushare: `HIGH-PRIORITY CONTROLLED-EVIDENCE CANDIDATE` because realtime + current-day replay are officially exposed.
- TickFlow: `HIGH-PRIORITY CONTROLLED-EVIDENCE CANDIDATE` because full service + current-day intraday API are officially exposed and Stock Razor already has an optional adapter.
- TDX: `CONTROLLED-EVIDENCE / FALLBACK CANDIDATE`; protocol support exists but adapter/failure semantics need hardening.
- BaoStock: `HISTORICAL/BACKFILL/CROSS-CHECK CANDIDATE`, not realtime Currentness authority.

## Final governance conclusion

A-share intraday data acquisition is **not blocked by lack of external providers**. It is blocked by the absence of a provider-semantic contract strong enough to turn a minute row into authoritative session progress.

Therefore the correct next step is:

`SOURCE CAPABILITY -> CONTROLLED SEMANTIC EVIDENCE -> INDEPENDENT REVIEW -> CAPABILITY ADMISSION -> Currentness integration`

not:

`method exists -> pick TTL -> call it fresh`.

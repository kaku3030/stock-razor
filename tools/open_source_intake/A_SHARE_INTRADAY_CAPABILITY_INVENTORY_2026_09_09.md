# A-share Intraday Capability Inventory — 2026-09-09

Status: HARVEST / PROVIDER-CAPABILITY EVIDENCE. Non-production.

## Purpose

Separate four claims that are often incorrectly collapsed:

1. an external library/service **documents** 15m/60m support;
2. Stock Razor's current adapter **implements** that capability;
3. the provider timestamp/bar-finality semantics are **verified**;
4. the provider is qualified as **Currentness authority**.

Only (4) may drive authoritative intraday currentness. Library capability alone is insufficient.

## Current Stock Razor capability truth

### PyTDX

Current `data_provider/pytdx_fetcher.py`:

- its comments document TDX `get_security_bars` categories including 15-minute and 1-hour values;
- the actual current `_fetch_raw_data()` path is fixed to daily category `9`;
- `DataCapabilityService` currently registers PyTDX only for `kline.daily`.

Classification:

- external/protocol 15m support: `KNOWN_METHOD_CAPABILITY`;
- Stock Razor `bars.15m`: `NOT_IMPLEMENTED_IN_CURRENT_ADAPTER`;
- Stock Razor `bars.1h`: `NOT_IMPLEMENTED_IN_CURRENT_ADAPTER`;
- timestamp/finality semantics: `UNVERIFIED`;
- Currentness authority: `NO`.

Do not advertise an implemented intraday capability merely because the underlying TDX protocol can request it.

### AKShare

Current Stock Razor capability registry exposes AkShare for realtime quote, daily K-line, index daily, market overview and CN financial snapshot. It does not currently expose explicit `bars.15m` / `bars.1h` capabilities.

Official AKShare documentation currently documents:

- `stock_zh_a_hist_min_em`: A-share Eastmoney minute history with `period` choices `1/5/15/30/60`;
- `stock_zh_a_minute`: Sina-backed A-share/index minute data with `1/5/15/30/60`;
- `index_zh_a_hist_min_em`: Eastmoney index minute history with `1/5/15/30/60`.

Important Harvest interpretation:

- AKShare is an adapter/library identity, not one upstream lineage;
- Eastmoney and Sina routes must remain separate upstream identities;
- documented minute data is recent/history-oriented and does not by itself establish realtime finality or publication latency;
- official AKShare interface docs show a timestamp column but do not, in the evidence reviewed here, contractually define start-boundary vs end-boundary semantics for 15m/60m bars.

Classification:

- external 15m/60m capability: `DOCUMENTED`;
- current Stock Razor explicit intraday capability: `NOT_REGISTERED / NOT_PROVEN`;
- timestamp/finality semantics: `UNVERIFIED`;
- Currentness authority: `NO` pending adapter + provider-semantics validation.

Official source:
- https://akshare.akfamily.xyz/data/stock/stock.html
- https://akshare.akfamily.xyz/data/index/index.html

### Tushare

Tushare's current official documentation materially changes the candidate landscape compared with a history-only assumption.

Documented current services include:

- `rt_min`: A-share realtime minute data, frequencies `1MIN/5MIN/15MIN/30MIN/60MIN`;
- `rt_min_daily`: one A-share's accumulated same-day realtime-minute bars, same frequency set;
- `rt_etf_min` / `rt_etf_min_daily`: ETF realtime minute and same-day accumulated minute bars;
- historical minute services also support 1/5/15/30/60m but are separate paid permissions and are processed after close.

Current Stock Razor `TushareFetcher` is not yet evidenced here as exposing those new realtime-minute methods through Radar's normalized intraday adapter contract.

Classification:

- external A-share realtime 15m/60m capability: `DOCUMENTED`;
- external ETF realtime 15m/60m capability: `DOCUMENTED`;
- entitlement: `REQUIRES_EXPLICIT_PERMISSION / COST`;
- Stock Razor implementation: `NOT_YET_PROVEN`;
- timestamp boundary/finality semantics: `UNVERIFIED`;
- Currentness authority: `CANDIDATE_ONLY`.

Official sources:
- https://tushare.pro/document/2?doc_id=374 (`rt_min`)
- https://tushare.pro/document/2?doc_id=457 (`rt_min_daily`)
- https://tushare.pro/document/2?doc_id=416 (`rt_etf_min`)
- https://tushare.pro/document/2?doc_id=470 (`rt_etf_min_daily`)
- https://tushare.pro/document/1?doc_id=234 (historical minute permissions/processing)

### BaoStock

BaoStock-family API documentation/wrappers consistently expose 5/15/30/60-minute historical K-line capability. Available documentation also describes the minute `time` field as a bar-end timestamp in common BaoStock-compatible surfaces, but the primary official knowledge-base page was not cleanly machine-readable in this audit.

Therefore evidence discipline is:

- historical 15m/60m support: `SUPPORTED / CROSS-DOCUMENTED`;
- bar-end timestamp semantic: `PARTIAL / NEED_PRIMARY_OR_CONTROLLED_CONFIRMATION`;
- realtime capability: `NO` for current Radar purpose;
- Currentness authority: `NO`;
- best role: historical backfill / reconciliation / cross-check.

Primary service site:
- https://www.baostock.com/

Do not promote a timestamp semantic to provider VERIFIED solely from third-party wrappers.

### TickFlow

Stock Razor already contains optional `TickFlowFetcher` with realtime quote, daily K-line, index and market-review surfaces. The current capability registry does not expose explicit 15m/1h bars.

Classification:

- current daily/realtime quote capability: `IMPLEMENTED`;
- 15m/1h capability: `NOT_REGISTERED / NEED SDK CAPABILITY AUDIT`;
- Currentness authority: `NO` until explicit bar capability + timestamp/finality semantics are validated.

## Capability-state vocabulary

Future DataCapability work should not use a single boolean `supports_intraday`.

Recommended states per provider/capability:

- `EXTERNAL_DOCUMENTED`
- `ADAPTER_IMPLEMENTED`
- `NORMALIZATION_VALIDATED`
- `TIMESTAMP_SEMANTICS_VERIFIED`
- `FINALITY_SEMANTICS_VERIFIED`
- `ENTITLEMENT_VERIFIED`
- `CURRENTNESS_AUTHORITY_ELIGIBLE`

These are cumulative evidence dimensions, not compensatory scores.

## Proposed explicit Radar capabilities

A-share provider registry should eventually model at least:

- `bars.15m.history`
- `bars.60m.history`
- `bars.15m.realtime`
- `bars.60m.realtime`
- `calendar.trading_day`
- `calendar.session_shape`
- `corporate_actions`
- `adjustment_factors`
- `fundamentals.snapshot`
- `fundamentals.point_in_time`

`bars.1h` may be used as an application alias, but provider contracts should record the provider-native 60-minute semantic explicitly rather than assuming every vendor's "1H" construction is identical.

## Current Harvest priority

1. **Tushare realtime minute** — capability looks strong enough to justify a bounded provider-semantics / entitlement audit. Do not integrate before timestamp/finality evidence.
2. **AKShare Eastmoney/Sina minute** — useful historical/reconciliation candidates; separately audit timestamp semantics and upstream lineage.
3. **TDX/mootdx path** — harvest maintained protocol implementation/tests before extending the archived-pytdx-backed current adapter.
4. **BaoStock** — history/backfill/reconciliation role; no realtime currentness role.
5. **TickFlow** — inspect SDK capability before assuming minute bars exist.

## Currentness authority rule

> `EXTERNAL_DOCUMENTED` or `ADAPTER_IMPLEMENTED` is never sufficient for `CURRENTNESS_AUTHORITY_ELIGIBLE`.

Before any A-share 15m/60m provider becomes currentness authority, require controlled evidence for:

- timestamp timezone and boundary (start/end/provider-defined);
- forming-bar inclusion and mutation;
- completed-bar distinguishability/finality;
- normal A-share lunch break behavior;
- 09:30 open and 15:00 close bucket construction;
- half-day/temporary-closure policy where relevant;
- suspended/zero-trade instrument behavior;
- publication delay distribution;
- entitlement/rate-limit degradation behavior;
- source lineage/provenance.

Until then, the correct state is `CURRENTNESS_AUTHORITY_UNVERIFIED`, not a guessed TTL.

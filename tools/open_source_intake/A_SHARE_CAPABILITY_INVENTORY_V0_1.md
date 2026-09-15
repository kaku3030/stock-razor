# A-Share Provider Capability Inventory V0.1

Status: FOUNDATION / GAP INVENTORY. Non-production.

Source baseline:

- current Stock Razor `main` provider capability definitions;
- current Stock Razor provider adapters;
- upstream `ZhuLinsen/daily_stock_analysis@089d9d26d68f8b839ea5a74a3784e4402925f8b7`;
- A-share Harvest and Upstream Migration Matrix dated 2026-09-09.

Purpose: make A-share provider work capability-driven and cross-window auditable. This is an inventory, not permission to route trading/analysis through a provider.

## 1. Important correction

A-share provider infrastructure is already present in current `stock-razor/main`.

Current `DataCapabilityService` declares provider families including:

- Efinance;
- AkShare;
- Tencent;
- PyTDX;
- Baostock;
- Tushare;
- TickFlow.

Current `data_provider/` also contains the provider strategy layer and adapters.

Therefore the task is **not** to create a new provider registry. The task is to harden and extend the existing one under Radar Foundation invariants.

## 2. Existing declared CN capabilities

Current capability definitions expose approximately:

| Provider | `quote.realtime` | `kline.daily` | `index.daily` | `market.overview` | `financial.snapshot` |
| --- | --- | --- | --- | --- | --- |
| Efinance | CN | CN | — | CN | — |
| AkShare | CN | CN | CN | CN | CN |
| TencentFetcher | — | CN | CN | — | — |
| PyTDX | — | CN | — | — | — |
| Baostock | — | CN | — | — | — |
| Tushare | CN | CN | — | CN | — |
| TickFlow | CN | CN | CN | CN | — |
| YFinance | — | CN | CN | CN | — |

This table records declared route capability, not provider quality or semantic trust.

## 3. Existing realtime sub-source model

Current CN realtime tokens include:

- `efinance`;
- `akshare_em`;
- `akshare_sina`;
- `akshare_qq`;
- `tencent`;
- `tushare`;
- `tickflow`.

Important lineage observation:

- `akshare_em` = AkShare adapter / Eastmoney upstream family;
- Efinance is also Eastmoney-oriented;
- `akshare_sina` = AkShare adapter / Sina upstream family;
- `akshare_qq` and current `tencent` realtime routing may use AkShare/Tencent upstream semantics;
- `TencentFetcher` is separately declared for daily/index routes and must not be conflated with a realtime token merely sharing the word Tencent.

Current code even maps the realtime token `tencent` to the AkShare provider family for capability reporting. This is evidence that the project already contains two different identity axes which should become explicit rather than overloaded into one `source` string.

## 4. Required provider identity split

Freeze candidate for A-share provider metadata:

### `adapter_id`

Which Stock Razor adapter/code path executed?

Examples:

- `akshare`
- `efinance`
- `tencent_direct`
- `tickflow`
- `tushare`
- `tdx_mootdx`

### `upstream_lineage_id`

Which external data family/backend supplied the evidence?

Examples:

- `eastmoney`
- `sina`
- `tencent`
- `tickflow`
- `tushare`
- `tdx_public_server`
- `baostock`

### `endpoint_id`

Which endpoint/capability path was used?

Examples:

- `eastmoney_push2_spot`
- `tencent_quote`
- `tdx_security_bars`
- `tickflow_quote`
- `tickflow_daily_kline`

### Why

Without this split:

- two wrappers over Eastmoney can be falsely treated as independent corroboration;
- `tencent` can mean adapter or upstream depending on route;
- circuit-breaker and reconciliation evidence become ambiguous.

## 5. Target Radar A-share capabilities

### A. `quote.realtime`

Need:

- current price;
- OHLC/current-day high-low where supplied;
- volume/amount;
- provider timestamp when authoritative;
- source/upstream provenance;
- timeout/failure evidence;
- session/currentness qualification separate from fetch success.

Existing candidates:

- Tencent upstream/direct or AkShare Tencent path;
- TickFlow;
- Efinance/Eastmoney;
- AkShare Sina;
- AkShare EM;
- Tushare where current entitlement supports it.

Gap:

- source lineage is not explicit enough;
- malformed vs missing normalization needs repair;
- currentness must not be reduced to TTL.

### B. `bars.intraday.15m`

Need:

- 15-minute OHLCV;
- exchange session/lunch-break semantics;
- interval-boundary semantics;
- suspension/zero-trade behavior;
- provider progress identity suitable for freshness/currentness;
- historical repair/backfill capability.

Current capability registry: **not explicitly declared**.

Candidate lanes:

- TDX-family maintained implementation;
- TickFlow if its current API/entitlement proves 15m support;
- selected AKShare endpoint as comparison/fallback after semantic testing.

Status: `P0 CAPABILITY GAP / NEEDS EMPIRICAL CONTRACT`.

### C. `bars.intraday.1h`

Same governance as 15m.

Current capability registry: **not explicitly declared**.

Candidate lanes:

- TDX-family;
- TickFlow if verified;
- selected secondary source for reconciliation.

Status: `P0 CAPABILITY GAP / NEEDS EMPIRICAL CONTRACT`.

### D. `bars.daily`

Existing mature multi-source path.

Candidates:

- Efinance;
- AkShare;
- Tushare;
- TickFlow;
- PyTDX currently;
- Baostock;
- Tencent direct fallback;
- YFinance fallback.

Required hardening:

- adjustment semantics;
- provider correction/revision tracking;
- authoritative trading calendar;
- malformed-vs-missing preservation;
- T+1 reconciliation;
- replace/reassess archived PyTDX dependency.

### E. `index.daily`

Existing declared routes include AkShare, Tencent direct, TickFlow, YFinance depending on index family.

Required hardening:

- keep registered-index route separate from generic stock route;
- explicit index family/venue semantics;
- do not infer one index source's quality from ordinary stock capability.

### F. `market.snapshot/breadth`

Existing market overview path includes TickFlow / AkShare / Tushare / Efinance family candidates.

Required hardening:

- snapshot timestamp/provenance;
- constituent universe identity;
- breadth denominator consistency;
- source fallback must not mix incompatible universes invisibly.

### G. `calendar.trading`

Current generic capability inventory does not expose a first-class CN trading-calendar dataset.

Need:

- SH/SZ/BJ coverage;
- full/partial session semantics where applicable;
- exceptional closures;
- no weekday/holiday heuristics;
- source/revision timestamp.

Candidates:

- structured provider such as TuShare/TickFlow if available;
- exchange/reference cross-check.

Status: `P0 FOUNDATION GAP` because intraday Currentness depends on session truth.

### H. `corporate.actions`

Need:

- ex-rights/ex-dividend;
- split/bonus/rights issue semantics;
- effective date vs announcement date;
- adjustment factors;
- revision provenance.

Candidates:

- TuShare;
- BaoStock;
- selected AkShare endpoints;
- TDX xdxr for comparison where maintained implementation exposes it.

Status: `P1 STRATEGY-LAB DATA INTEGRITY`.

### I. `financial.point_in_time`

Current `financial.snapshot` is not enough for historical Strategy Lab work.

Need:

- report period;
- announcement/publication time;
- restatement/revision handling;
- what information was knowable at simulation time.

Candidates:

- TuShare;
- BaoStock;
- AkShare structured endpoints.

Status: `P1 TEMPORAL-INTEGRITY GAP`.

### J. `sector.concept.breadth`

Existing upstream has strong support through AKShare/Eastmoney/TickFlow paths.

Need:

- board identity/version;
- constituent timestamp;
- provider lineage;
- avoid mixing board rankings and constituent universes from different timestamps without evidence.

Status: `ADAPT / RESEARCH RADAR PRIORITY`.

## 6. Provider-specific current disposition

| Provider / adapter | Current disposition |
| --- | --- |
| TickFlow | High-priority structured candidate; already integrated; empirically validate entitlement/timestamps/intraday support |
| Tencent direct | Keep/adapt for lightweight quote/daily/index paths; prove timestamp semantics |
| AkShare | Keep as multi-upstream adapter framework; require endpoint lineage and endpoint-specific health |
| Efinance | Keep/adapt, but classify Eastmoney lineage and do not treat as independent from AKShare EM |
| Tushare | Structured history/calendar/fundamental candidate; capability/cost/latency probe required |
| Baostock | History/backfill/reconciliation candidate; current service/package probe required |
| PyTDX | Do not expand archived dependency; harvest behavior/tests and evaluate maintained TDX implementation |
| mootdx / maintained TDX stack | Candidate replacement/extension for intraday 15m/1H and TDX fallback; empirical provider contract required |

## 7. Foundation invariants for every A-share capability

1. Fetch success never equals Data Health success.
2. `realtime` label never equals Currentness proof.
3. malformed non-empty provider values remain distinguishable from missing evidence.
4. elapsed timeout/cooldown logic uses monotonic time.
5. provider adapter identity and upstream lineage are separate.
6. fallback does not erase the failed-source evidence.
7. stale last-good/cache data cannot inherit a previous healthy permission silently.
8. session/lunch-break/suspension semantics are explicit before intraday stale/currentness decisions.
9. different wrappers over the same upstream do not count as independent reconciliation sources.
10. no provider is promoted globally; promotion is per capability.

## 8. Near-term engineering slices

### A0 — Identity/Inventory Slice

DOC/SCHEMA/TEST only:

- add capability IDs for `bars.intraday.15m`, `bars.intraday.1h`, `calendar.trading`, `corporate.actions`, `financial.point_in_time`, `sector.concept.breadth`;
- add `adapter_id / upstream_lineage_id / endpoint_id` contract;
- no routing behavior changes yet.

### A1 — Normalization/Data Health Slice

- make malformed-vs-missing contract reusable across provider adapters;
- preserve provider raw-quality evidence;
- monotonic circuit-breaker/cooldown state;
- stale-age telemetry cannot grant health/currentness.

### A2 — Intraday Provider Contract Slice

- compare maintained TDX lane, TickFlow availability, and one independent secondary source;
- prove 15m/1H boundary, lunch break, suspension and currentness semantics;
- build deterministic fixtures.

### A3 — Reconciliation Slice

- provider lineage-aware comparison;
- T+1 daily diff;
- intraday sampled cross-source diff;
- stale-good-state revocation;
- only then automatic fallback promotion.

## 9. Cross-window synchronization

For A-share work, the durable source order is:

1. `A_SHARE_DATA_PROVIDER_HARVEST_BATCH_2026_09_09.md`
2. `A_SHARE_UPSTREAM_PROVIDER_MIGRATION_MATRIX_2026_09_09.md`
3. `A_SHARE_CAPABILITY_INVENTORY_V0_1.md`
4. PR #31 Harvest Ledger.

Any other Stock Razor chat/development window should read these artifacts before proposing A-share interface changes.

## Governing sentence

> A-share integration is already broad; the next quality leap comes from proving capability semantics, provenance and currentness — not adding more wrappers.

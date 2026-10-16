# Stock Razor read-only MCP

This is a separate MCP facade for ChatGPT-facing market-data reads. It calls
the existing authenticated FastAPI snapshot endpoint and does not import the
legacy realtime-monitor MCP, create a provider, subscribe, seed data, access
OpenD, or expose trading/account operations.

## Tools

- `get_market_snapshots(symbols, timeframe="1m")`
- `get_market_bars(symbol, timeframe="1m", limit=1)`
- `get_livefeed_health()`

Every result is read-only and preserves `UNKNOWN` for entitlement,
provider finality, currentness, and controller generation unless the upstream
API supplies authoritative evidence. The current snapshot view exposes the
latest bar per available timeframe; it is not a historical bars API.

## Configuration

Inject these values through the process environment or a secret manager:

```text
STOCK_RAZOR_READONLY_API_BASE_URL=https://<private-read-api-host>
STOCK_RAZOR_SNAPSHOT_READ_TOKEN=<independent-read-only-secret>
STOCK_RAZOR_MCP_TRANSPORT=streamable-http
```

The token is sent as `Authorization: Bearer ...`; it is never placed in a URL
or committed to the repository. The API must remain behind HTTPS and the
OpenD ports remain localhost-only.

## ChatGPT connection status

The MCP process is code-complete for the current snapshot API but is not
automatically connected to this ChatGPT task. ChatGPT custom MCP apps require
developer mode and a user/admin-created app: provide the remote MCP endpoint,
choose authentication, scan tools, then test the draft app. A real
`CHATGPT_NATIVE_MCP_READ=PASS` requires a tool call from that configured app
returning AMD/QQQ data; local tests or an HTTP 200 do not establish it.

For a private server, use the supported Secure MCP Tunnel or an approved
HTTPS reverse proxy. Do not expose OpenD or the internal FastAPI service
directly.

## Budgeted secure tunnel smoke

GitHub Actions > AWS SSM Ops > secure_mcp_cost_smoke sends exactly ONE
OpenAI Responses API request through the existing tunnel and only allows
get_market_snapshots for AMD 15m. max_output_tokens=3000 and no API retry.
It cannot start providers or enable trading. The older secure_mcp_remote_e2e
action still performs SIX model requests, and is not a cheap quota check.

Per-request nonsecret logs: OPENAI_MODEL_CALLS_ATTEMPTED,
OPENAI_MODEL_CALLS_SUCCEEDED, OPENAI_INPUT_TOKENS,
OPENAI_CACHED_INPUT_TOKENS, OPENAI_OUTPUT_TOKENS and
OPENAI_USD_TOKEN_ESTIMATE (only when provider usage is available).
Absent usage or unexpected model gives OPENAI_TOKEN_COST_STATUS=UNKNOWN.

USD estimates use conservative GPT-6 Astra reference rates:
$10/M uncached input, $1/M cached input and $50/M output tokens
(Standard tier). This token-only estimate is NOT the OpenAI invoice,
does not include other tool/infrastructure charges, and is NOT an
authoritative current balance. Reconcile against OpenAI Platform usage/cost.
For illustration, $9.99 divided by a measured $0.20 per call
supports about 49 calls if nothing else consumes credits.

An E2E probe success does not prove native ChatGPT app installation,
24/7 uptime, freshness, clock skew, Radar admission or live trading.

## MCP smoke failure diagnostics (privacy-safe)

The first metered smoke, GitHub Actions run 37962759162, returned HTTP 200
and token usage (1746 input, 150 output), yielding a **token-only estimated**
USD 0.024960. Its MCP data assertion **failed**; no AMD bars or quotes were
verified. This is **not** a provider failure proof and not a successful E2E.

The cost smoke now logs allowlisted `MCP_DIAG_*` fields:

- `RESPONSE_STATUS`: completed/incomplete/failed/UNKNOWN;
- `TOOL_CALLS` and `LIST_TOOLS`: counts to distinguish discovery from execution;
- `TOOL_ERROR`, `TOOL_NAME_MATCH`, `TOOL_STATUS`: only flags / fixed statuses;
- `TOOL_OUTPUT_SHAPE`: fixed code such as TEXT_NOT_JSON, EMPTY_CONTENT,
  OBJECT_NO_SNAPSHOTS, SNAPSHOTS_OBJECT, MULTIPLE_CONTENT_ITEMS;
- `SNAPSHOT_SCHEMA`: PASS only for a read-only response containing AMD;
- `MARKET_DATA_PRESENT`: PASS only with nonempty quote or bars; EMPTY otherwise.

The smoke interprets either a direct JSON snapshot result or the standard
MCP typed `content: [{type: text, text: ...}]` envelope. It never logs raw
tool outputs, responses, credentials or error messages. Failure remains FAIL
without promoting entitlement, currentness, ChatGPT-native connection or any
trading admission.

Cost/runway must be reconciled from API billing. User-reported starting
balance of USD 9.99 was not queried from OpenAI billing, and is not a
continuously refreshed balance. As an **illustration only**, 9.99 / 0.024960
is ~400 similar model calls before other fees or activity. The test calls are
metered individually by the full E2E workflow; model calls are independent of
market-data API calls or EC2 time. No remote probe is automatically triggered
by a code merge.

## 2026-10-10 canonical remote smoke schema correction

Read-only cloud E2E GitHub Actions run 37964659098 used exact
main 4f27a7f8306b99c7a7c1304d4245099ee14759af.
Responses HTTP/model call and `get_market_snapshots` discovery/call
**passed** (1 MCP call, tool status completed, no tool error).
Reported 1770 input + 184 output tokens; token-only
cost estimate **USD 0.026900**. Probe still failed because the
validator expected the older `stock_razor_readonly_mcp.py` facade
`{read_only, snapshots: [...]}`.

**Source-of-truth:** production secure tunnel targets
`http://127.0.0.1:8000/mcp`, served by
`realtime_monitor/readonly_mcp_server.py` (installed using
`ops/aws/install_readonly_mcp.sh`). That implementation calls
`data_provider/us_canonical_runtime_reader.read_us_market_snapshots`,
which returns `{ok, status, data_available, symbols: {'US.AMD':
{counts, latest: {'15m': bar}}}, ...}`. Its tool takes `symbols`,
not a `timeframe` parameter. The earlier validator therefore
made a **false-negative schema assertion**; this does not prove the
actual returned data was populated or fresh.

The corrected single-call probe decodes standard typed MCP content,
accepts only the canonical US.AMD 15m schema, reports a fixed
`SYMBOLS_OBJECT` output shape, requires fail-closed runtime flags,
requires source `status=PASS` and source age 0..120 s,
and requires a nonempty 15m latest bar and `data_available=true`.
Older facade responses may be categorized `LEGACY_FACADE`
but cannot pass this exact-runtime probe. Source snapshot freshness
does **not** establish last bar's market-session currentness or
provider-to-Radar latency; those gates remain independent and blocked.

No extra OpenAI API or cloud calls were made while implementing this fix.
The two previous token-only estimated model charges sum to USD 0.051860,
but billing account balance and any other project/API activity remain
unknown.

## Fast chat watchlist scan (2026-10-10)

New **`get_us_quick_scan(symbols=["AMD","NVDA","TSLA","QQQ"])`** is a
strictly read-only, **compact projection** of the existing
`read_us_fast_research_brief`. It reuses the existing fail-closed
snapshot + Radar aligned cache reads, without another provider query,
model inference, or admission change. It includes source sequence,
runtime, SHA, market/radar ages, bar closure metadata, per-symbol
1m/5m/15m/1h close and explicit per-bar `is_closed`,
`is_complete`, `quality_flags`, 1d/1h/15m trend and quality,
support/resistance, research score, watch conditions and risk flags.

Prefer one `get_us_quick_scan` tool call for routine mobile watchlist
review. Request the larger `get_us_research_brief` only when detailed
indicator values or additional evidence are required. Never infer
trade-ready data from aggregate `bar_closure=PROVEN`: each bar's
finality must be checked. Missing or stale sources and SHA/runtime/
sequence mismatch fail closed with no per-symbol research output.

**Performance claims:** the one-call brief observed in ChatGPT on
2026-10-10 took about 5.9s end-to-end for four symbols and returned
about 23KB. This is one observation, not an SLA or a controlled
comparison. The new compact endpoint reduces returned fields and
expected model token load; actual tunnel RTT and p50/p95 speedup are
**NOT VERIFIED** until deployed and benchmarked on matched requests.
The source SHA reported by the runtime must be checked against
deployed revision separately. OpenAI Responses API token costs do not
directly measure ChatGPT plugin token accounting.

## CN TickFlow historical readback through an existing ChatGPT tool

The canonical cloud MCP already registers `get_cn_tickflow_research_data`, but
older ChatGPT app snapshots can expose only `get_cn_market_data`. An **opt-in**
compatibility route lets that existing action read the *same AWS-local,
provider-native TickFlow research cache* without rescanning tools:

- Call `get_cn_market_data(symbol="TICKFLOW:159611.SZ", timeframe="15m", limit=3)`.
- Or use `TICKFLOW:518880.SH` and `timeframe="60m"`.
- Prefix matching is exact; other symbols continue the existing
  Eastmoney-primary/Tencent-fallback reader, unchanged.
- The prefix strips only `TICKFLOW:`, and the existing cache reader retains
  its symbol/period/limit allowlist, freshness checks and all fail-closed gates.
- `research_mode="historical_only"` is forced. `PASS_HISTORICAL_ONLY`
  **never** means live-feed continuity, provider bar finality, canonical
  Source Arbiter admission, Radar entry, Paper readiness or trade permission.
- This adds no network access to TickFlow from MCP and does not install any
  new cloud service. Calls only read the periodically updated private cache.

The independent AWS loopback smoke workflow
`.github/workflows/verify-tickflow-cloud-mcp-loopback.yml` verifies the actual
MCP HTTP protocol and original tool, using four bounded historical calls; it
never reports provider prices or secrets to public Actions logs.

### Explicit intraday TickFlow progress through the same connected tool

After an owner-reviewed MCP SHA deployment, use
`get_cn_market_data(symbol="TICKFLOW:PROGRESS:159611.SZ", timeframe="15m", limit=4)`
(or `518880.SH`, `5m` / `60m`) for the cache reader's bounded
`session_progress` path, which checks the complete sequence of Shanghai due-grid labels through
the latest due boundary, independently of the requested `limit`. A missing
intermediate or final due label returns `BAR_LABEL_BEHIND_SESSION`, never
`PASS_RESEARCH_ONLY`. Historical-only may instead return
`DUE_LABEL_PRESENT_WITH_GAPS_HISTORICAL_ONLY`; this is not complete
current-session evidence. The cloud cache is read only; **no extra
paid-provider I/O** occurs.

`PASS_RESEARCH_ONLY` is **not** an exchange-closed candle or actionable
market signal. Vendor-float research rows retain explicit
`ohlc_validation=VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY`; both
`bar_finality` and `currentness` stay unverified. No automatic
fallback to Tencent/Eastmoney and no source/Radar/Paper/trade admission.
The original `TICKFLOW:<symbol>` remains historical-only; ordinary
symbols stay on their explicit legacy provider route. `1d` is
deliberately invalid for `session_progress`.

### Fast cloud TickFlow research read

The already-connected ChatGPT `get_cn_market_data` tool also accepts
`symbol="TICKFLOW:BATCH"` with `limit=1..24`, or `symbol="TICKFLOW:FULL"`
with `limit=1..240`. The `timeframe` parameter is ignored for these exact
literals. BATCH returns the four held ETFs' 15m and 60m frames; FULL returns
the four held ETFs' 1m/5m/15m/60m/1d frames, in one remote MCP round trip.
It makes **zero provider requests**. Every frame uses the same historical-only
TickFlow private cache reader. The batch requires every requested frame to pass and its
`repo_sha` and `sequence` to match; stale/misaligned results never return a
partial price-bearing batch. Ordinary `get_cn_market_data("159611.SZ",...)`
retains the original provider.

All returned rows remain research-only with unverified finality, unverified
live currentness, no source/Radar/Paper/Live trading admission. During market
hours `TICKFLOW:BATCH` is **not** evidence of WS continuity or a current
completed bar; check each frame's `expected_grid_progress`.

### Fast TickFlow compact watchlist

For routine read-only watchlist refreshes, use the already connected
`get_cn_market_data(symbol="TICKFLOW:FAST", limit=1)` action. It reads
exactly one native 15m and 60m historical OHLCV row for each of the four
held ETFs through the validated batch
`TICKFLOW:BATCH` cache reader, retaining source SHA and sequence alignment.
It returns compact native `t/o/h/l/c/v/a` values, amount availability,
OHLC float-validation status, session grid progression and explicit
`bar_finality=NOT_VERIFIED` / `is_partial_bar=true` on every row.

The added `read_ms` field measures in-process **MCP-local reader** execution
only. It does **not** measure chat-to-connector network RTT, cloud polling
latency, SDK/network/provider latency, or actual exchange finality.
Any stale, malformed or mismatched source fails closed without returning
partial price-bearing data. The response never asserts Radar/Source Arbiter
or trading admission; use regular `TICKFLOW:BATCH` when historical depth
is needed. This is not a replacement for D1/5m or a validated live WS feed.

### Single-call full TickFlow multi-timeframe research

The ChatGPT `get_cn_market_data(symbol="TICKFLOW:FULL", limit=40)` route
returns the four held ETFs, each with 1m, 5m, 15m, 60m and 1d historical
native rows in **one** cloud MCP tool call. Twenty frame reads must share a single cache SHA
and sequence and all pass; any stale/misaligned frame rejects the whole
batch without leaking partial prices. This API never contacts TickFlow
directly, never claims provider bar finality, and does not authorize
Radar, Source Arbiter, Paper or Live Trade.

The existing `TICKFLOW:BATCH` (15m+60m, limit<=24),
`TICKFLOW:FAST` (compact 15m+60m latest) and normal Eastmoney/Tencent
read routes remain unchanged. The provider's daily 00:00 timestamp is
a DATE stamp only, not a BAR_END assertion; daily remains historical-only.

## Read-only US OpenD historical D1 (guarded compatibility route)

For currently connected ChatGPT tools, call `get_market_bars(symbol="NVDA", timeframe="1d", limit=5)` after the MCP revision is deployed. This special 1d path reads the existing `/run/stock-razor-us-livefeed/daily-history.json` cache from Futu/OpenD; it makes **zero** provider, account or order requests. The default intraday 1m/5m/15m/1h routes are unchanged.

The D1 reader checks livefeed health, exact runtime/commit lineage, cache age, symbol, source safety flags, strictly increasing prior-session dates and finite OHLCV. Missing/stale/mismatched evidence fails closed. A successful response uses `PASS_HISTORICAL_ONLY`, not regular `PASS`. **The current New York trading date is excluded; the reader neither confirms today's D1 close nor proves native provider finality.** The response retains `provider_finality=NOT_VERIFIED`, `current_session_daily_bar=NOT_AVAILABLE`, `source_arbiter_admission=BLOCKED`, `radar_admission=BLOCKED`, `paper_auto_ready=false` and `live_trade=false`.

A merged PR or green unit test does **not** prove the cache exists or that this new code is deployed to AWS. A direct connected MCP readback is required before calling the route operational, and current-day D1 completion remains a separate unverified capability.

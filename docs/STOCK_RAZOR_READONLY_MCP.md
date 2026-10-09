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

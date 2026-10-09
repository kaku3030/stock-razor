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

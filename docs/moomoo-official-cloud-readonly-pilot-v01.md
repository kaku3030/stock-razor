# moomoo Official Cloud MCP/REST Pilot — Read-only Acceptance V0.1

> **Research runbook, NOT an authorization, deployment, login or order.**
> Prepared 2026-10-11 for STOCK RAZOR Main Control / Engineering.
>
> Gate defaults: `PAPER_AUTO_READY=NO`; `RADAR_ADMISSION=BLOCKED`;
> `SOURCE_ARBITER_ADMISSION=BLOCKED`; `LIVE_TRADE=NO`.

## Verified vendor references

- Hosted Streamable HTTP MCP: `https://mcp.moomoo.com/mcp`. [MCP overview](https://open.moomoo.com/mcp-docs/overview), [quick start](https://open.moomoo.com/mcp-docs/quick-start).
- MCP OAuth consent permissions: `quote:read`, `quote:write`, `trade:read`, `trade:write`; token typically expires after 2 hours and may require reauthorization following >14 days inactivity. [Authentication](https://open.moomoo.com/mcp-docs/authentication).
- REST API: `https://webapi.moomoo.com`, OAuth 2.1 + PKCE. The REST **simulated account list GET may automatically create accounts on first call**. [REST getting started](https://open.moomoo.com/api/overview/getting-started), [simulation accounts](https://open.moomoo.com/api/sim-trade/account-list).
- Provider FAQ notes regional/account-tier feature limitations. [MCP FAQ](https://open.moomoo.com/mcp-docs/faq).

The above describe provider capabilities, **not** verified support for this user's Japan brokerage account, not entitlement, not streaming latency, and not identity equivalence between REST/MCP, OpenD and the mobile Paper account.

## Phase 0 — no network, automatic or account mutations

1. Freeze existing OpenD branch; preserve proven working feeds until replacement has independent data provenance and 15m/60m closure tests.
2. Use only official provider-hosted endpoints; verify hostname/TLS; **never** place access/refresh tokens, account IDs, authorization codes or PKCE verifiers in the PUBLIC stock-razor repo, GitHub Actions logs or PR comments.
3. Enforce the offline scope guard `assess_moomoo_readonly_oauth_grant` for any future pilot. Scope projection is not proof of token authenticity.
4. Confirm supported geography and API entitlement for Japan **before** promising access to the linked mobile moomoo account. Do not infer parity from a matching display name.

## Phase 1 — user-authorized quote-only pilot

- Obtain the user's separate, explicit action in the official OAuth consent screen. Request **only** `quote:read`.
- Reject `trade:write`, `quote:write`, `trade:read`, wildcard `accid:*`, unknown scopes, and any unexpectedly exposed mutation tools.
- The OAuth client, not GitHub CI, must verify issuer, PKCE S256, state, callback, access expiry and independent account entitlement.
- Store tokens in the approved secrets system/keychain, **not GitHub workflow outputs or plain environment variables**.
- Inspect provider-visible tool names/method semantics after consent. Adopt a **positive allowlist** of known quote-only tools; deny everything else, even if its name contains `get` or `read` unexpectedly.
- With separate provider request approval, collect bounded quotes and 1m/5m/15m/60m bars on a small watchlist, plus provider source timestamp, time zone, full-bar closure, delay, entitlement and rate limits. Never promote a market signal based solely on a healthy MCP heartbeat.

## Phase 2 — separately approved trade-read trial

- The user must explicitly consent again to **only** `quote:read trade:read accid:<expected numeric ID>`; no live/mutation scopes or wildcard accounts.
- Brokerage real-account holdings may be sensitive; do not query them without account-scope clarity. Never infer that the REST Paper account matches mobile Paper or OpenD simulation.
- **DO NOT invoke** `GET /api/v1.0/sim-trade/accounts` until the user authorizes possible *automatic creation of simulated accounts* on the first GET.
- Where available, read back only account-level metadata, balance, positions and orders from one verified US SIMULATE account. Bind every observation to session identity and 60-second TTL; require unique matching account. No broker order mutation.
- Use read-only reconciliation preflight (BALANCE/POSITIONS/OPEN_ORDERS/FILLS) as a **negative gate** only. A consistent set is still not authentication proof.
- Any mismatch, region rejection, stale timestamps, duplicated accounts, nonflat positions, open orders, OAuth expiry, 401/403/429, incompatible mobile parity or unknown provider failure → **BLOCK** and preserve existing safe path.

## Phase 3 — supervised Paper only (future)

- Not part of this PR. Requires separate approval and provenance for source freshness, account ownership, expected order ID, lifecycle receipts, duplicate/idempotency gates, kill switch, max notional/quantity and terminal reconciliation.
- No transition to real account is permitted by Paper success alone. Explicit human confirmation and a separate risk review would still be necessary.

## Outcome report — privacy-safe template

Only output enumerated statuses, source SHA, observed_at UTC, bounded latencies, known error reason codes, and presence/absence of vendor permissions. **No** token fragments, account IDs, filled order details, real-account balances or raw API dumps. Report `QUOTE_READ_AVAILABLE`, `ACCOUNT_READ_UNVERIFIED`, `PAPER_MATCH_UNVERIFIED`, `MOBILE_PARITY_UNVERIFIED`, `SIGNAL_ADMISSION_BLOCKED`, `LIVE_TRADE_NO` until observed evidence warrants narrower factual statuses.

This document and scope validator perform **zero** provider/API, OAuth, AWS, broker, scheduler or notifier I/O.

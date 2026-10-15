# STOCK RAZOR — Unified Provider Billing & Renewal Watch

**Owner: Engineering Autonomy / Billing Monitoring**. This is the single
cloud-run provider cost and renewal notification entrypoint. The main/trading
windows should not create parallel billing schedulers. No user PC is needed.

## One location / one cadence

- GitHub Actions: `.github/workflows/provider-billing-renewal-watch.yml`
- Automatic check once daily at **01:20 UTC / 10:20 JST**. Explicit
  `workflow_dispatch` offers offline dry-run (default) and real read-only
  `dry_run=false` report.
- On Mondays the owner receives an informational **unified report**. Threshold
  warnings can send on any day.
- Preferred existing channel: `DISCORD_RADAR_WEBHOOK_URL`, then
  `DISCORD_WEBHOOK_URL`, then existing `TELEGRAM_BOT_TOKEN` and
  `TELEGRAM_CHAT_ID` as fallback. GitHub Actions outbound Discord **HTTP 403**
  was independently observed; a configured secret does not prove delivery.
  Telegram may be the only working channel until the network/provider issue is
  resolved. This code does not create or reveal any webhook/token.
- Do **not** publish raw account balances or AWS billing data in a publicly
  accessible GitHub Action log or commit. Unified financial detail is sent only
  to owner-configured private alert channels.

## Provider coverage / evidence quality

| Service | Evidence | What is NOT known |
|---|---|---|
| OpenAI API | Official org Admin Costs/Usage **GET**: UTC month-to-date spend, requests, input/output tokens. Requires `OPENAI_ADMIN_KEY`. | Actual prepaid balance. The Costs API is not a wallet balance endpoint. |
| DeepSeek / Engineering Autonomy | Official **GET /user/balance** reports `OK/LOW/EMPTY/UNAVAILABLE`, using the same `DEEPSEEK_API_KEY` as Coding V1.1. Every request is read-only and uses **no generation tokens**. Aider's input/output tokens and rate-based USD estimates remain a **separate per-run** artifact in Coding V1.1, not 30-day authoritative provider billing. | The unified wallet checker does not provide full historical usage/tokens or an actual billed-total ledger. The DeepSeek developer console shows these separately. |
| AWS | Dedicated OIDC AWS job queries **Cost Explorer month-to-date UnblendedCost** in USD, reports provisional/estimated status; optional user-defined monthly budget alerts when spend reaches 80%. | Actual credits, Free Tier balance, remaining prepaid funds, finalized invoice. These cannot be inferred from Cost Explorer unblended spend. |
| TickFlow Expert | `TICKFLOW_RENEWAL_DATE`: 30/14/7/3/1/0 days before renewal and overdue; monthly subscription, no API wallet. | No date means **UNKNOWN**, not a guessed next month. |
| OpenD | Confirmed as free **in the user's current configuration**; no balance or paid expiry monitoring. | Cloud availability/connectivity is tracked by the separate OpenD market-data acceptance workflows. |

DeepSeek default prepayment alerts: CNY <=10 / USD <=2 across wallets (one usable
currency is sufficient; a zero USD bucket with CNY credit is not "empty").
Its **paid coding safety gate** remains in Coding V1.1 and blocks on
LOW/EMPTY/UNAVAILABLE/UNKNOWN. The unified monitor does not run Aider.
A 503 or unreadable wallet = UNKNOWN, never "zero balance".

AWS requires the existing GitHub OIDC `StockRazorGitHubOpsRole` and
`ce:GetCostAndUsage` access, with no new long-lived AWS keys. Only the
**isolated AWS cost job** receives OIDC write permission; OpenAI/DeepSeek keys
are only present in the separate unified report job. If AWS Cost Explorer
denies permission or is disabled, report **UNKNOWN / NOT_AUTHORIZED**; do not
silently claim cost $0. No IAM or Cost Explorer subscription toggles are made.

**AWS paid-API opt-in (disabled by default):** AWS Cost Explorer
`GetCostAndUsage` incurs **US$0.01 per request** for the primary billing
view (AWS official pricing). Querying once a day is approximately US$0.30
per 30-day month before taxes. This integration does **not** perform that
request until the owner explicitly sets repository Action variable
`AWS_COST_EXPLORER_ENABLED=true`. Omitted / false leaves AWS monthly
usage=UNKNOWN and never assumes $0. Setting this flag is permission to
incur that small API usage charge; the owner must approve it separately.
`AWS_MONTHLY_BUDGET_USD` is a **different** variable that controls the
user-defined spend-alert threshold, not the API opt-in.

## Configuration

GitHub Actions repository secrets (already available where configured):

- `DEEPSEEK_API_KEY` — balance GET and the independent manual Coding V1.1.
- `OPENAI_ADMIN_KEY` — required for org Costs and Usage; normal project
  `OPENAI_API_KEY` is **not** sufficient. No admin secret = UNKNOWN.
- `DISCORD_RADAR_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — existing notification
  fallbacks, never include values in PRs or messages.

Repository **Variables**:

- `TICKFLOW_RENEWAL_DATE` — YYYY-MM-DD actual next renewal date.
- `OPENAI_MONTHLY_BUDGET_USD` — alert when 80% of owner-defined spend limit.
- `AWS_COST_EXPLORER_ENABLED` — optional explicit paid-query opt-in; default false.
- `AWS_MONTHLY_BUDGET_USD` — optional, same 80% alert. Without it actual
  AWS spend may be shown but the budget *remaining* is UNKNOWN.
- `OPENAI_CREDIT_SNAPSHOT_USD` and `OPENAI_CREDIT_SNAPSHOT_DATE_UTC` —
  optional owner-entered **estimate**, never authoritative balance.

No auto-recharge, AWS configuration change, new IAM grants, API generation,
Aider scheduling, deployment, or trading. `RADAR_ADMISSION=BLOCKED` /
`LIVE_TRADE=NO` remain unaffected.

## Testing and exception paths

- Cloud tests: `python -m pytest -q tests/test_provider_billing_renewal_watch.py tests/test_unified_provider_billing_watch.py`.
- Provider dry-run: `python scripts/provider_billing_renewal_watch.py --dry-run`
  makes **no network/API calls** and does not send any notifications.
- `engineering-autonomy-deepseek-balance-watch.yml` is retained as an
  **explicitly manual diagnostic only** (no separate 12-hour schedule).
- Every financial amount is sourced from the vendor API or an explicitly
  user-entered budget. No fabricated balance, renewal date, exchange rate,
  service fee, or currency conversion.

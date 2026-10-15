# STOCK RAZOR Provider Billing & Renewal Watch

**Status:** Cloud GitHub scheduled watcher / read-only / no trading. No dependency on Windows staying awake.

## Coverage and exact meanings

- **OpenAI API**: official Admin organization Costs and Completions Usage **GET** endpoints; UTC month-to-date USD spend, request count, input/output tokens. Requires a separate **organization Admin API key** as GitHub Actions repository secret `OPENAI_ADMIN_KEY`. A normal OpenAI project API key is not sufficient for these endpoints. No chat prompt/completion is sent, so this watcher makes no paid AI-generation requests.
- **Actual OpenAI prepaid remaining credit:** **UNKNOWN** — Costs API reports charges, not the authoritative current prepaid balance. It cannot reveal automatic credit additions, refunds, timing/expirations. Do not label budget remainder as actual account balance. If the owner explicitly sets BOTH `OPENAI_CREDIT_SNAPSHOT_USD` and `OPENAI_CREDIT_SNAPSHOT_DATE_UTC` (UTC midnight snapshot), monitor reports **PREPAID ESTIMATE** = owner-provided snapshot - since-snapshot Costs, never authoritative. Reset both inputs after each top-up. The real balance is at the OpenAI API billing dashboard. A configured monthly budget `OPENAI_MONTHLY_BUDGET_USD` is also the owner's limit for alerts, not a billable credit balance.
- **TickFlow Expert:** monthly plan with **date** warning only. Set GitHub Actions variable `TICKFLOW_RENEWAL_DATE` as **next renewal / coverage deadline YYYY-MM-DD**. Alerts at 30, 14, 7, 3, 1, 0 days and overdue (on first and weekly overdue day). The program **never guesses one month after purchase**, never assumes a renewal succeeded, never reads an API balance or triggers any payment.
- **OpenD:** explicitly excluded (no paid subscription to track).
- **DeepSeek:** outside this V0.1 request; its separate balance/usage guard is not changed.

## Live cloud setup

The workflow is `.github/workflows/provider-billing-renewal-watch.yml`: GitHub scheduler daily at **01:20 UTC / 10:20 JST**; each Monday sends a usage/renewal summary, and any day sends threshold warnings. Uses existing GitHub Actions secret `DISCORD_RADAR_WEBHOOK_URL` to send to the user's Discord alert channel; if that endpoint fails, attempts the separately configured existing `DISCORD_WEBHOOK_URL`. Neither credential is logged. A timeout can produce duplicate delivery when fallback retries, but never silently claims an alert arrived if both fail. No new Discord destination or stored plaintext webhook. Explicit manual dispatch has `dry_run=true` as the safe default. No spend auto-recharge, no trading, no extra paid vendor polling. Outside of the configured Admin key and date, OpenAI spend/tokens and TickFlow expiry **remain UNKNOWN** and a weekly configuration warning is emitted.

Secrets and variables must be added to GitHub repository **Settings → Secrets and variables → Actions**; do not paste API keys into chats, .env, PR comments or public code. The schedule cannot be assumed operating until the PR is merged, daily cron has triggered and a real Discord delivery run has passed.

## Safety and operations

Cloud Actions uses `contents: read`, no AWS access, broker access, orders, or account mutation. Vendor error HTTP bodies and provider keys are not printed; limited fixed codes only. Notification HTTP errors cause nonzero workflow failure. No watchdog may declare source/currentness/Radar admission; they remain BLOCKED independently.

Run offline: `python scripts/provider_billing_renewal_watch.py --dry-run` and `python -m pytest -q tests/test_provider_billing_renewal_watch.py`.

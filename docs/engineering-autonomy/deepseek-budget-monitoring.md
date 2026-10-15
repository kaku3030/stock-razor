# DeepSeek budget and token monitoring — Engineering Autonomy

This is an **internal STOCK RAZOR GitHub Actions feature**, NOT a ChatGPT reminder.
It uses the existing repository secret `DEEPSEEK_API_KEY`; never paste the key
into an issue, chat, or source file.

## Balance — official source, not an estimate

- Official DeepSeek API: `GET https://api.deepseek.com/user/balance`.
- Uses exactly one authenticated **GET**, no chat-completion requests and no generation tokens.
- Supported currencies: CNY and USD; no automatic FX conversion.
- A healthy balance is required before the **manually confirmed** Engineering
  Autonomy Coding V1.1 can run its paid native provider probe or Aider agent.
- Defaults: **LOW at ≤ CNY 10 or ≤ USD 2** (when the usable balance falls below
  threshold across all present currencies); **EMPTY at 0**; **UNAVAILABLE**
  if DeepSeek reports `is_available: false`. Low, empty, unavailable and
  unknown/unreadable API results all **block paid coding (fail closed)**.
  Thresholds are configurable in reviewed source, not via untrusted prompts.
- Only a categorical status and available currency codes enter runner logs.
  The raw JSON response, precise balance, token, and Authorization header
  are never written to GitHub logs, issues, cache or artifacts.

## Recharge alerts (Discord, not ChatGPT tasks)

- The separate **Engineering Autonomy DeepSeek Balance Watch (no model calls)**
  workflow checks balance every 12 hours and on manual dispatch. No LLM tokens.
- The repository currently has **GitHub Issues disabled**, so notifications use
  Discord instead. Store your Discord channel's webhook URL in GitHub Actions
  repository secret `DISCORD_WEBHOOK_URL`; do not paste it into code.
  Optionally set repository variable `STOCK_RAZOR_DISCORD_USER_ID` to your
  numeric Discord user ID to get a direct mention. Otherwise enable channel
  notifications in Discord to see alerts on your phone.
- Only categorical LOW / EMPTY / UNAVAILABLE / UNKNOWN status is sent.
  `UNKNOWN` **does not** mean zero balance and sends a distinct monitor-error
  warning. The DeepSeek key and exact wallet amounts never leave the balance
  checker. If the webhook is unconfigured, the alert step fails visibly,
  not a false claim that a notification was delivered.
- While low, the watcher reminds you at most twice per day (every 12 hours).
  No auto-refills or secret/IAM changes. It is a monitor-only schedule, **not**
  an autonomous coding or trading schedule.

## Tokens and spending

- Coding V1.1 supplies `--analytics-log` and `--no-analytics` together:
  Aider writes a **local-only** ephemeral analytics log, with no analytics
  telemetry sent to third parties.
- After each attempt, a strict parser extracts only Aider `message_send`
  input, output and total token counters, number of requests, and any Aider
  **estimated USD cost** from the event. **Never** upload or print the raw
  analytics events: they can contain identifiers and provider metadata.
- The **sanitized per-run** JSON artifact is retained for 30 days, and the
  GitHub Actions job summary shows the counters. If Aider emitted no usage
  event, it reports `NO_DATA`, not "0 tokens used".
- The cost from Aider is a *model-rate estimate*, **not a billed amount**.
  DeepSeek /user/balance is the authoritative real funds signal. Differences
  between snapshots may include other API keys, manual top-ups, or grants;
  never claim the two exactly reconcile.
- This is **per-run telemetry**, not yet a cross-run billing ledger or total
  historical account usage service. No retrospective totals can be asserted.

## Operator workflow

1. Create a Discord webhook in your STOCK RAZOR alerts channel; set its URL
   as repository Actions secret `DISCORD_WEBHOOK_URL`.
2. Optional: set repository variable `STOCK_RAZOR_DISCORD_USER_ID` to your
   numeric Discord user ID so Discord can mention you. Do not share secrets
   in chat.
3. Find `Actions → Engineering Autonomy DeepSeek Balance Watch (no model calls)`
   to run a manual **GET-only** balance check, or let the 12-hour check run.
4. On a Discord LOW/EMPTY/UNAVAILABLE alert, inspect or top up the DeepSeek
   developer console. No payment is triggered automatically.
5. After a confirmed Coding V1.1 attempt, inspect its `generate` job summary
   or `autonomy-deepseek-usage` sanitized artifact for request/token counters.
   The native provider probe and the coding workflow remain independently
   manually confirmed; low/unknown balance still fails closed.

Safety: no auto-run of the Coding V1.1 workflow, no AI PR auto-merge, no
deployment/IAM change, and no live trading permissions.

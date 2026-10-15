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

## Recharge alerts

- The separate **Engineering Autonomy DeepSeek Balance Watch (no model calls)**
  workflow checks balance every six hours and can also run on manual dispatch.
- It may **only** read DeepSeek balance and open, update or close a **single
  de-duplicated GitHub Issue** titled
  `STOCK RAZOR: DeepSeek API recharge required`. It assigns the repo owner
  for GitHub notification; on recovery it closes the alert. Issue text carries
  only LOW / EMPTY / UNAVAILABLE status, not the exact amount.
- `UNKNOWN` (API 503, timeout, malformed response, missing key, etc.) **does
  not pretend the balance is zero** and does not generate a "recharge" claim.
  The monitoring job fails visibly instead.
- **Enable GitHub notifications for assigned Issues in the app** if you want
  phone push alerts. GitHub issue delivery depends on your GitHub notification
  settings; it is not a ChatGPT-native push.
- Schedule is **monitor-only**. It cannot trigger Aider, merge any PR, deploy,
  start Radar/Paper or make a trade. It is separate from the disabled
  long-running engineering/coding schedulers.

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

1. Find `Actions → Engineering Autonomy DeepSeek Balance Watch (no model calls)`
   to run an optional *read-only* balance check, or let the six-hour check run.
2. If the assigned recharge Issue opens, top up the **DeepSeek API account**
   through the official developer console. No automatic charges or refills.
3. When the account is healthy, the monitoring Issue is closed on the next
   check. A healthy balance does **not** mean the DeepSeek API model is
   available; the separate V1.1 native provider health probe remains required.
4. To inspect usage of a confirmed Coding V1.1 attempt, view its `generate`
   job step summary or `autonomy-deepseek-usage` sanitized artifact.

Safety: no auto-run of the Coding V1.1 workflow, no AI PR auto-merge, no
deployment/IAM change, and no live trading permissions.

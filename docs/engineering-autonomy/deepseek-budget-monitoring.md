# DeepSeek budget and token monitoring — Engineering Autonomy

This is an **internal STOCK RAZOR GitHub Actions feature**, NOT a ChatGPT reminder.
It uses the existing repository secret `DEEPSEEK_API_KEY`; never paste the key
into an issue, chat, or source file.

## Balance — official source, not an estimate

- Official DeepSeek API: `GET https://api.deepseek.com/user/balance`.
- Uses exactly one authenticated **GET**, no chat-completion requests and no generation tokens.
- Supported currencies: CNY and USD; no automatic FX conversion.
- A healthy balance is required before the **manually confirmed** Engineering
  Autonomy Coding V1.1 can run its paid Aider agent.
- Defaults: **LOW at ≤ CNY 10 or ≤ USD 2** (when the usable balance falls below
  threshold across all present currencies); **EMPTY at 0**; **UNAVAILABLE**
  if DeepSeek reports `is_available: false`. Low, empty, unavailable and
  unknown/unreadable API results all **block paid coding (fail closed)**.
  Thresholds are configurable in reviewed source, not via untrusted prompts.
- Only a categorical status and available currency codes enter runner logs.
  The raw JSON response, precise balance, token, and Authorization header
  are never written to GitHub logs, issues, cache or artifacts.

## Unified recharge alerts (not ChatGPT tasks)

The single scheduled cost/expiry report is
`.github/workflows/provider-billing-renewal-watch.yml`, every day at
**10:20 JST**. It combines **DeepSeek** official funds, **AWS** estimated
Cost Explorer spend, **OpenAI** usage, **TickFlow** renewal date and
**OpenD** (free configuration). The DeepSeek-specific Balance Watch workflow
is now **manual-diagnostic only** and must not run another 12-hour schedule.

The shared provider watch uses pre-existing owner-configured
`DISCORD_RADAR_WEBHOOK_URL` / `DISCORD_WEBHOOK_URL` and Telegram fallback
secrets. GitHub cloud runners previously received Discord HTTP 403, so real
delivery must be checked, and a configured webhook is not delivery proof.

If DeepSeek is LOW/EMPTY/UNAVAILABLE, the unified monitor alerts and Coding
V1.1 separately blocks further paid generation. On API 503/timeout it reports
UNKNOWN and does not call it zero or automatically recharge. The official
wallet amount, key, and raw response never enter public Actions logs.

## Tokens and spending

Coding V1.1 proposes a **CNY 5** per-run budget, **240 seconds**, **2 completion
requests**, **20,000 input tokens**, and **4,000 output tokens**. The spending
limit is **not yet proven enforceable**: the official balance GET is not
provider-side per-run capping evidence. A repository variable equal to
`provider-enforced:cny:5` can be spoofed and is **never accepted** as proof.
The workflow now fails closed at `cost-cap-check` **before installing Aider**
until an authenticated, enforceable upstream spend-cap mechanism is implemented
and independently validated in a separate reviewed PR.

The analytics watchdog detects accumulated requests/tokens *after* the
provider has handled a request. Polling does **not** bound a single in-flight
completion's tokens or actual charge; per-request output limits and trustworthy
pre-request budget enforcement still require implementation and tests. No
current V1.1 run is authorized to consume model tokens under this gate.

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

1. Open `Actions → STOCK RAZOR Provider Billing & Renewal Watch`. Its
   scheduled 10:20 JST run is the **single central monitor**.
2. A manual run defaults to `dry_run=true` (no provider calls, no message).
   A user-confirmed `dry_run=false` queries read-only sources and sends a
   sanitized report through the existing notification fallback chain.
3. If the DeepSeek wallet is LOW/EMPTY, top up via the DeepSeek developer
   console. The next daily check confirms whether funds recovered.
4. In Coding V1.1, see the `generate` step summary and
   `autonomy-deepseek-usage` sanitized artifact for **per-run** Aider token
   counts and estimated cost (30-day retention). The unified billing watcher
   cannot assert complete historical DeepSeek token spend.
5. The dedicated DeepSeek Balance diagnostic workflow remains available
   manually (including a clearly labelled Discord-only test), but is not an
   extra recurring billing schedule.

Safety: no auto-run of the Coding V1.1 workflow, no AI PR auto-merge, no
deployment/IAM change, and no live trading permissions.

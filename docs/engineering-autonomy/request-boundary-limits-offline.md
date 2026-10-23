# DeepSeek request-boundary budget planning — offline only

**Status: RESEARCH / NOT_ADMITTED.** This is a preparation module, not a
payment authorization, verified tokenizer, or a replacement for the reviewed
paid-coding gate in PR #815. It does not modify any GitHub Actions workflow.
It must **not** be imported into a production paid runner as sole protection.

## Scope and invariant

`engineering_autonomy/deepseek_request_plan.py` constructs and reserves
strictly limited chat-completion request envelopes, without using credentials,
making network calls, or launching Aider.

* Exact model: `deepseek-flash` only.
* Up to two reservations, no streams and no declared retries.
* Combined **claimed** input tokens <=20,000. **Input counts are not certified**:
  the module does not implement or verify the DeepSeek tokenizer.
* Combined maximum output-token reservations <=4,000. Every envelope forces a
  concrete `max_tokens` field and non-thinking mode. The provider API documents
  `max_tokens` as a maximum output, but the library does not verify the wire.
* Payloads are text-only, with 64 messages / 64 KiB serialized message cap;
  rejects tool calls, images, malformed types and invalid encodings.
* Reservation happens before returning the envelope. There are no refunds
  based on after-the-fact analytics.
* The admitted request is returned as **immutable UTF-8 JSON bytes**, not a
  mutable dictionary. This prevents modifying `max_tokens` in-place after
  reservation. A later caller could still parse and forge a *different* byte
  string, so only a future independently enforced network transport using the
  **exact emitted bytes** would provide on-wire assurances.
* Within a single Python process, a lock protects the shared request/input/
  output counters from simultaneous reservations. Exact-envelope fingerprints
  reject accidental replay attempts without storing or logging message text.
  A caller that changes model parameters can produce a different envelope;
  this is not a proof that arbitrary SDK retries are blocked.
* Separate Python processes, instances, hosts or runners do NOT share state;
  the independent-ledger regression test demonstrates this limitation.
* A sanitized summary labels all input counts as **UNVERIFIED** and cannot be
  presented as an actual bill or provider-wallet statement.

## Adversarial regression cases

`tests/test_engineering_deepseek_request_plan.py` exercises 35 cases:
third request, cross-request input/output overspend, one-shot output overrun,
invalid model, streaming, retry, bool/negative/unknown token counts, unsupported
messages/roles/modalities, oversized and invalid UTF-8 content, text-leakage
prevention, same-envelope replay, post-reservation mutation and concurrency.
These are offline in-process fixture tests.

## Real localhost HTTP mock (zero provider cost)

`engineering_autonomy/deepseek_loopback_mock.py` proves that the *exact
prevalidated JSON bytes* can cross an actual **localhost HTTP** boundary,
without transmitting real DeepSeek credentials. It only allows literal
`http://127.0.0.1:<port>/v1/chat/completions`, disables urllib environment
HTTP proxies and redirects, always uses a hard-coded fake API key, and
requires a one-time dispatch claim bound to the admitted byte fingerprint.
A failed HTTP attempt consumes its dispatch claim; no retry occurs. Mock
responses must include structurally valid usage within the claimed input
and reserved output or fail closed. Returned counters are explicitly marked
`SIMULATED_LOOPBACK_ONLY`, never official provider usage.

`tests/test_engineering_deepseek_loopback_mock.py` runs a real local
`ThreadingHTTPServer` and tests exact wire bytes, sealed-request replay,
concurrent attempts, forged `max_tokens`, nonlocal destination rejection,
proxy/credential isolation, 3xx redirect denial, 429/500/503 no-retry, and
oversized or invalid response accounting. The fake HTTP server stays on
127.0.0.1 and never calls the DeepSeek provider.

**Unchanged hard limit:** the mock transport is not on Aider's execution
path. Aider can still use its own network/SDK and provider credentials if
those are exposed to its process. The mock only demonstrates an integration
seam; it does not isolate the paid agent, verify its input token counts,
provide a cross-process/global ledger or enforce provider-side cost.

A future guarded sandbox would need to run Aider without the real provider
key, configure an OpenAI-compatible API base to point solely at a local
gateway, keep the real provider key only inside that gateway, and enforce
network egress isolation independently of CLI configuration. Aider documents
custom OpenAI-compatible endpoints here:
https://aider.chat/docs/llms/openai-compat.html

The local mock transport is NOT suitable for real network forwarding.

## Required before any paid run

1. Bind all outgoing Aider/model requests to a *single*, reviewed outbound
   transport; remove direct provider credentials and external network bypasses
   from the Aider child.
2. Prove the **provider-recognized** input token count with a validated
   tokenizer or an independent provider preflight. Claimed counts here do not
   satisfy that requirement; unknown counts must fail closed. DeepSeek's
   official token-usage docs state that its downloadable *offline tokenizer*
   only estimates usage and provider response usage is authoritative:
   https://api-docs.deepseek.com/quick_start/token_usage/ .
   In particular, comparing a local string length or a tokenizer estimate
   to 20,000 is not an invoice-grade hard cap. A complete wire-level guard
   must account for roles, message formatting, and any internal tool prompts.
3. Enforce remaining `max_tokens` **at the actual HTTP request boundary**,
   including any tool use, hidden retries, internal probes and multiple SDK
   paths. Reject unexpected model aliases and mutable thinking configurations.
   Aider's own advanced settings documentation states that it does *not*
   enforce token limits; model metadata and LiteLLM settings do not establish
   upstream request-level cost control. See
   https://aider.chat/docs/config/adv-model-settings.html .
4. Obtain independently verified **provider-side** CNY 5 hard-cost
   protection or an auditable, conservative per-call spend bound under a
   provider-verifiable pricing and usage contract. Neither a GitHub variable
   nor a balance GET proves such a cap. The official **Chinese** Flash
   pricing page *does* quote CNY prices: peak cache-miss input CNY 2 / million
   and output CNY 8 / million as checked on 2026-10-16
   (https://api-docs.deepseek.com/zh-cn/quick_start/pricing/).
   Under independently enforced 20k billed input + 4k billed output tokens,
   the illustrative price calculation is CNY 0.072. **This is not a hard
   budget guarantee**: input token counts are untrusted, the actual Aider
   outbound requests are not intercepted, upstream retries are unknown and
   the provider explicitly reserves the right to change prices. No FX is
   necessary when quoting the CNY page, but the actual wallet deduction and
   any future rate changes still require verification.
5. Verify official before/after balance, provider usage and the exact cloud
   deployment SHA in one isolated one-shot canary; retain sanitized evidence.
6. Only after independently reviewed checks pass, propose a **separate**
   opt-in, manually confirmed change to paid-run admission. Do not silently
   enable schedules, production deployment, auto-merging or trading.

Documentation used for API envelope semantics:
https://api-docs.deepseek.com/api/create-chat-completion/
https://api-docs.deepseek.com/quick_start/pricing/

This module intentionally stays disconnected from
`.github/workflows/engineering-autonomy-coding-v1-1.yml`, which retains its
own fail-closed policy while PR #815 awaits review.

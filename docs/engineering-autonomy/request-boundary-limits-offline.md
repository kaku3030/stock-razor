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

`tests/test_engineering_deepseek_request_plan.py` exercises 33 cases:
third request, cross-request input/output overspend, one-shot output overrun,
invalid model, streaming, retry, bool/negative/unknown token counts, unsupported
messages/roles/modalities, oversized and invalid UTF-8 content, and text
leakage prevention, same-envelope replay and simultaneous attempts. They are
offline fixture tests only.

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
4. Obtain independently verified **provider-side** CNY 5 hard-cost protection
   or an auditable, conservative pricing/currency maximum supported by an
   upstream enforced spend limit. Neither a GitHub variable nor a balance
   GET proves such a cap. Provider prices can change. The official public
   Flash pricing page currently presents **USD/token** quotes, whereas this
   project's one-shot limit is specified in **CNY**; conversion and the
   authoritative charged currency cannot be inferred from a static price
   table: https://api-docs.deepseek.com/quick_start/pricing/ .
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

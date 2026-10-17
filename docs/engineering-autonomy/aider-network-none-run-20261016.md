# Pinned Aider real CLI in no-network Docker — 2026-10-16

**Scope:** engineering acceptance only; **not** a provider fee cap, not
production admission, not TickFlow/OpenD/Paper. Paid coding stays BLOCKED.

## Exact observed result — first actual Aider isolation run

- GitHub Actions:
  https://github.com/kaku3030/stock-razor/actions/runs/38870726663
- Host runner builds pinned `aider-chat==0.86.2` in a **test-only Docker
  image** before launching the tested container.
- Actual model execution is inside `docker run --network none --read-only`,
  with dropped capabilities, no real credentials and a fake OpenAI-compatible
  server on container-local `127.0.0.1`. Only a fixed dummy key is passed.
- Baseline success: **1** locally observed HTTP request, Aider exit 0,
  fake Authorization correct, endpoint `/v1/chat/completions` correct.
- Baseline fake HTTP 503: **24 HTTP requests in 65 seconds** before the
  process-level timeout; Aider exit 124. Critically,
  `LITELLM_MAX_RETRIES=0` and `--no-stream` did **not** prevent these extra
  calls in the pinned real client.
- In both scenarios, **`max_tokens` was absent** in the emitted request JSON.
  The CLI-side output budget and after-the-fact analytics thus cannot prove a
  per-call bound. These are actual observed request wire shapes, not guesses.

**Do not run this pinned CLI against a provider key with only these flags.**

## Follow-up protection in this research branch

The offline smoke server now has three separately visible modes:

1. `success`: show actual Aider-to-loopback compatibility (fake completion).
2. `strict-gate`: reject an absent or invalid `max_tokens`, wrong path,
   wrong authorization, unexpected stream or >4,000 output tokens **before
   counting any attempted upstream forwarding**. On policy violation, stop
   Aider rather than trusting its retry settings.
3. `retry-budget-gate`: permit one simulated upstream HTTP 503; deny any
   following retry attempt and stop the child immediately at the gateway
   limit. Always report the number of observed attempts, the number admitted
   by the mock and the number denied.

The sandbox script also reads Linux IPv4 and IPv6 default-route tables to
fail closed unless the actual running namespace has **no default route**. This
check complements but does not replace Docker's `--network none` isolation.

The mock **never forwards to any provider**. An accepted mock-upstream count
is not an actual paid API call. No existing Aider production runner has been
rewired, and multiple separate processes/runners would still need a durable
shared ledger if deployed.

## Required production admission steps

- Configure Aider with a dummy key and local gateway, then enforce a real
  **network namespace / egress restriction** for the Aider child. Leaving
  the actual provider key or Internet available to Aider is unsafe.
- Use real provider credentials **only in a hardened gateway**, never the
  agent. Reject missing, malformed or overly large on-wire `max_tokens`.
- Meter and enforce **all** attempts (including SDK automatic retries)
  before forwarding. A returned 503 cannot silently generate 24 billable
  upstream attempts.
- Implement independently verified input-token counting and concurrency-safe
  durable budget ledger; a caller-claimed number is not enough.
- Confirm an enforceable provider-side CNY 5 ceiling and current CNY token
  pricing, and reconcile sanitized server-side usage after each bounded run.

The next experimental GitHub CI result must show the **exact branch head**
before any PASS claim. No paid model execution is authorized by this document.

## Controlled mock-gateway follow-up — CI PASS

- Exact workflow: [run 38871440215](https://github.com/kaku3030/stock-razor/actions/runs/38871440215),
  job ID `116876216653`, head
  `efc5169ce92c652b2083b2c079dcb8d8d1dd6b78`.
- Docker `--network none` process reports
  `AIDER_NETNS=ONLY_LOOPBACK` by inspection of actual container interfaces.
  On no-network Linux images the IPv6 route file can legitimately be absent;
  the guard allows that only when no non-loopback interface is visible.
- **Normal Aider**: HTTP attempts 1, mock-accepted 1, denied 0, exit 0.
- **Strict missing-cap rejection**: HTTP attempts 1, mock-upstream accepted
  **0**, blocked 1, Aider terminated (exit -15).
- **Simulated first-provider-503**: Aider attempted 2 HTTP requests;
  mock-upstream accepted **1**, the retry was blocked **1**, Aider terminated.
  `AIDER_INTERNAL_RETRY_OBSERVED=True`.
- Every first request had correct mock-only Authorization, loopback endpoint
  and non-stream shape, and **NO `max_tokens`**. This confirms an independent
  gateway is required to set/reject the upstream limit; CLI flags alone do not.
- Overall status: `AIDER_ISOLATION=GATE_FAIL_CLOSED_LOOPBACK_PASS;`
  `PAID_CODING=BLOCKED`. The GitHub Actions job completed **SUCCESS**.

This is a **real pinned Aider executable**, not a stub client, but both the
gateway and any simulated upstream are *test-only* and in the isolated
container. The numeric `ACCEPTED_MOCK_UPSTREAM` counter does **not** mean a
paid provider request; model provider traffic is impossible by container
network isolation. Also note that a simple rejection gateway has not yet
proved it can modify missing `max_tokens` into a safe forwarded upstream
request, nor has it proved trusted input billing. Keep production closed.

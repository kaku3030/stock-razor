# TickFlow paid-history preflight hardening (2026-10-11)

**Status: offline contract only. No paid provider query.**

This change extends the already merged #581 contract with a thread-safe reservation
on a *single shared* `PaidHistoryBudget` object. It also refuses malformed
requests before the transport is called or quota is reserved: invalid windows,
non-TickFlow source, duplicate/blank/padded symbols, or batches over 200 symbols.
The 200-symbol conservative minute-batch cap comes from the user-provided Expert
package screenshot; it is not a verified account-level entitlement or billing grant.

## Remaining admission blockers

The budget object is **in-memory, single process, non-persistent**. Neither this
lock nor a rate limit shown on a plan page is a global spending guarantee, and
neither covers multiple AWS processes, retries, alternate callers, monetary pricing,
or a provider's hidden quota/billing policy. A real cloud run requires separately
verified account entitlements and billed-unit prices, a shared durable request
reservation and invocation identity, an explicit spending approval, and sanitized
provider response crosschecks. Without those facts, paid execution remains blocked.

`SOURCE_ARBITER_ADMISSION=BLOCKED`; `RADAR_ADMISSION=BLOCKED`;
`PAPER_AUTO_READY=NO`; `LIVE_TRADE=NO`.

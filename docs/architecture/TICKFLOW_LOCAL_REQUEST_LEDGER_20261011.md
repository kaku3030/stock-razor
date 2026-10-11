# TickFlow paid-history reservation: local SQLite fence

**RESEARCH / OFFLINE only, default disabled; not authorized to spend.**

#581 and #585 already provide a single-process budget and pre-transport
request validation. This incremental isolated module provides a SQLite
`BEGIN IMMEDIATE` unit reservation with duplicate-request-ID rejection,
a default-disabled ledger and no rollback/refund of reservations on provider
errors. It supports concurrent callers **only if they use the same local
database file**. It is intentionally not attached to an AWS transport.

**Limitations**: Not safe across independent EC2 instances or separate
databases; does not implement provider-side billing/monetary costs, rate
limiting, retries, distributed leasing, quota refresh or a provider-admission
token. The Expert plan's 60 batch requests/min and 200 symbols/request are
not evidence of remaining account credits or a prepaid financial guarantee.

Before AWS paid experiments, verify account entitlement, per-request charges,
monthly billing cap, provider quota, an explicit authorized request count,
and cloud-wide atomic coordination or a proven single-owner deployment.
No TickFlow network call is permitted just because a local reservation exists.

`PAPER_AUTO_READY=NO`; `RADAR_ADMISSION=BLOCKED`;
`SOURCE_ARBITER_ADMISSION=BLOCKED`; `LIVE_TRADE=NO`.

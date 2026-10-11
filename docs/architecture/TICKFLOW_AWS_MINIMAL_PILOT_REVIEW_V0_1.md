# TickFlow Expert minimal cloud history pilot (review only)

This is a zero-I/O proposal validator. It does not open TickFlow, retrieve
history, reserve quota, enable payments, deploy AWS, or promote source data.

Based on the operator's Expert plan screenshot, the first pilot proposes:
one batch request at most, one closed trading day or less, maximum five ETFs,
a 1/5/15/30/60-minute timeframe, and an interval within 365 calendar days.
The account entitlement, exact monetary billing unit/ceilings, and request
approval must be independently confirmed; plan-page rate limits are not a
statement of prepaid credits or willingness to spend.

Even if all three confirmations are passed in, REVIEW_ONLY is the maximum
status and never authorizes any transport. A later AWS implementation needs
verified immutable budget evidence, shared durable request accounting, one
approved invocation identity, isolated credential scope, precise output
crosschecks and a hard kill switch.

RADAR_ADMISSION=BLOCKED; SOURCE_ARBITER_ADMISSION=BLOCKED;
PAPER_AUTO_READY=NO; LIVE_TRADE=NO.

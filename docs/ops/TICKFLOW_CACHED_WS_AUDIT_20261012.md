# TickFlow WS read-only AWS cache audit — 2026-10-12

The isolated TickFlow Expert SDK smoke has already performed real AWS REST
quotes, 1/5/15/30/60m history and depth successfully under the user's
monthly ¥199 Expert package; the new bounded WebSocket run #38204799914
ran **10 seconds during China lunch**, reporting connection and local
subscribe **CALL PASS**, **zero callbacks**, with no claim of a broken
provider or qualified live feed. This is expected in a closed session.

The existing `audit-existing-tickflow-quote-cache.yml` retrieves an
already-sanitized cache from the fixed AWS instance with zero new TickFlow
requests. Previously it reported only the REST quote call and symbol count.
This patch also projects source-pinned WS operation state, integer callback
counts, initial snapshot candidates and post-initial timestamp candidates,
and enum-only local connect/subscribe results, **always**
`ws_provider_live_qualified=false`.

Evidence cannot be adopted from an earlier code revision. With an
incorrect expected original probe SHA, the audit returns NOT_VERIFIED,
ws_operation UNKNOWN and zero projected counts. Missing/malformed provider
ACK or falsely asserted latency qualification fails the cache audit shut.
A read-only SSM audit cannot ever prove broker subscription ACK, server
freshness, signal admission, full-day K-line closure or trade permission.

All publicly rendered fields are finite enumerations, booleans or bounded
counters; provider raw prices, symbols, quotes, timestamps, credentials and
account records are not rendered. Adversarial tests **execute** the
actual embedded remote Python code on synthetic files and cover wrong SHA,
closed-session no events, malformed claim, leaked fields and invalid counts.

No AWS service deploy/restart, WS subscription, credential fetch, new
paid provider query or order is executed by the PR. Future active-market
WS live probe must be separately dispatched with bounded research
duration and user authorization; actual source admission remains BLOCKED.

`PAPER_AUTO_READY=NO`; `RADAR_ADMISSION=BLOCKED`;
`SOURCE_ARBITER_ADMISSION=BLOCKED`; `LIVE_TRADE=NO`.

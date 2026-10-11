# OpenD protected baseline guard — 2026-10-12

**Scope: read-only candidate planning, not provider subscription authority.**

The existing AWS US livefeed starts a fixed baseline of nine streams using one
OpenQuoteContext and LiveFeedRuntimeBridge. Until dynamic subscription ownership
and provider-side quota are independently accepted, all nine started streams
are treated as *protected* when comparing Radar's proposed candidate pool.

The pure observer `plan_readonly_subscriptions` now accepts an explicit
`protected` set of SemanticStreamKey values. It refuses a plan when a protected
stream is not part of the acknowledged baseline, or the requested target omits
one. Such a refusal publishes no proposed additions or removals.
Malformed, duplicated, excessively large, or unsupported protected keys also
fail closed. Changes to unprotected candidates can still be previewed; any
additions continue to require independent fresh quota evidence.

The AWS installer passes `protected=tuple(streams)` to its existing observer.
It does **not** subscribe/unsubscribe, open a second provider session, deploy
itself, or give Radar admission. This protects the inherited fixed monitored
universe from disappearing in a future dynamic candidate refactor, rather
than claiming production dynamic subscriptions are already functional.

Validation: synthetic unit tests plus the existing installer Python AST tests
in GitHub CI. **Real AWS runtime on the older revision is not updated by merge;
a separately controlled deployment and cloud acceptance remain necessary.**

`PAPER_AUTO_READY=NO`
`RADAR_ADMISSION=BLOCKED`
`SOURCE_ARBITER_ADMISSION=BLOCKED`
`LIVE_TRADE=NO`

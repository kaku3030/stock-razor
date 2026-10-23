# Shadow Observation Assembly Seam V0.1

This is a Research/Shadow assembly seam. It does not claim a complete Shadow
runtime and does not change Production permission or execution behavior.

## Contract

`AgentOrchestrator` calls the assembly seam only after the final dashboard has
passed its existing normalization, risk application, and finalization boundary.
The adapter receives `run_id`, `instrument`, the frozen dashboard as an audit
reference, optional existing evidence IDs, optional existing strategy gate
results, optional producer-owned timestamps, and an explicitly injected
`ObservationCaptureWriter`.

The adapter returns an existing `Observation` shape and writes only through the
existing Observation Ledger writer. It does not calculate strategy, risk,
portfolio admissibility, execution feasibility, execution records, or market
timestamps. Missing values remain `None`; permission remains `UNKNOWN`.

## Identity and idempotency

The canonical identity payload is the sorted object containing
`contract_version`, `decision_boundary`, `instrument`, and `run_id`. The
`observation_id` is `sha256:` plus the SHA-256 digest of its canonical JSON
encoding. A retry with the same payload and record is idempotent in the
existing writer. A same-ID, different-record append fails loudly as a
conflicting duplicate.

## Timing and failure policy

Only caller-supplied timestamps are preserved. No wall clock is read and no
timestamp is inferred from dashboard generation, agent completion, or the
current bar. `UNKNOWN` source-event quality requires a missing source-event
timestamp, and the existing Ledger monotonicity and same-bar guards remain
authoritative.

Writer injection is opt-in, so existing production paths remain unchanged. A
writer I/O failure is recorded in runtime diagnostics and logged without
altering the already-frozen dashboard; an identity or conflicting-duplicate
contract error remains fail-loud. This seam is not a transaction around the
trading decision.

## Explicitly out of scope

Portfolio admissibility, execution feasibility, `ShadowExecutionRecord`,
complete causal timestamp production, new databases/queues/services, and any
Production permission mutation are later seams.

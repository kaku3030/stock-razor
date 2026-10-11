# TickFlow Cloud Historical Batch Safety Contract V0.1

**State: research-only, default-disabled, offline-verified contract.**

This slice defines a small boundary for a future paid TickFlow historical-data
batch caller. It is deliberately separate from `data_provider/tickflow_fetcher.py`,
the isolated cloud probe, and qualification owners. It does not create a
TickFlow client, read an API key, perform network I/O, change OpenD, write a
canonical cache, or authorize Radar, Source Arbiter, Paper, or live trading.

## Pre-transport paid-request gate

`data_provider/tickflow_history_contract.py` accepts a caller-owned transport
only after all of the following are true:

- the explicit budget is enabled;
- the per-request cost is a positive known integer;
- `budget_remaining` is known and covers the cost;
- `quota_remaining` is known and covers the cost.

The default budget is disabled. A missing budget or unknown budget/quota returns
`UNKNOWN` and makes zero transport calls. Exhausted budget/quota and the
default-disabled state return `BLOCKED` and make zero transport calls. A
successful preflight reserves both counters before the transport is invoked, so
a transport failure or an invalid response cannot silently restore spend.

## Independent response crosscheck

The caller must provide sanitized response metadata. The contract checks:

| Field | Required evidence |
| --- | --- |
| `request_window` | Response start/end exactly match the requested timezone-aware window |
| `symbols` | Returned symbol set exactly matches the requested set |
| `timestamps` | Timestamps are timezone-aware, in-window, and strictly increasing per symbol |
| `row_count` | Declared row count exactly matches returned row metadata |
| `source_consistency` | Response source, every row source, and explicit consistency field agree |
| `window_completeness` | Explicit `True`; missing evidence is `UNKNOWN`, not a complete window |

Any mismatch is `BLOCKED`. Any required unknown is `UNKNOWN`. Only all checks
passing returns `PASS`; this is contract evidence only, not provider
entitlement, freshness, finality, provenance qualification, or admission.

## Verification boundary

The tests use a fake transport and prove the refusal paths make zero calls,
quota exhaustion is fail-closed, cross-source metadata disagreement is blocked,
and unknown complete-window evidence remains `UNKNOWN`. They do not contact
TickFlow, validate a paid account, or perform cloud acceptance.

The existing safety state remains unchanged:

`PAPER_AUTO_READY` unchanged · `RADAR_ADMISSION` unchanged ·
`SOURCE_ARBITER_ADMISSION` unchanged · `LIVE_TRADE` unchanged.

# AWS acceptance for existing OpenD candidate observer — 2026-10-12

## Exact problem

Merged #591/#596 introduced read-only dynamic candidate **planning** into
the existing single-owner AWS US LiveFeed, but the historical
`verify_us_opend_livefeed.sh` acceptance script did not check this
heartbeat field. The deployment could appear to pass despite a missing,
crashing or malfunctioning dynamic observer.

This update adds a **fail-closed runtime deployment assertion** and
one fixed public deployment marker: `OPEND_CANDIDATE_PREVIEW=READONLY_PASS`.

## Acceptance contract

The verifier reads the existing heartbeat privately on the fixed AWS
instance and independently requires:

- The local LiveFeed bridge's acknowledged stream names equal the protected
  installed baseline. **These local ACKs are not broker-side subscription
  reconciliation or proof of live quote delivery.**
- The observer is present, its scope explicitly says only existing bridge
  acknowledgments, and its integer `provider_calls` and
  `subscription_changes` are exactly zero.
- Protected stream removals are empty. The existing fixed pool can produce
  `NO_CHANGE_PLAN` without additions. An optional proposed new candidate
  pool may be `BLOCKED` strictly because fresh provider quota is not
  independently verified; the observer MUST NOT imply mutation.
- No `PLAN_ONLY` new provider mutation, malformed input, unexpected
  observer exception or missing evidence may be mistaken for deployed
  feature acceptance.
- Radar and Source Arbiter remain BLOCKED; automatic Paper and live trading
  are false.

The existing #601 guarded workflow consumes this explicit marker as part of
remote acceptance and returns it through its already allowlisted, sanitized
SSM output. It does not echo raw heartbeat/account/K-line data into public
Actions logs. Synthetic tests execute the exact embedded acceptance segment
without connecting to AWS/OpenD, including malformed ACKs, quota-blocked
candidates and deliberate violations of each admission flag.

## Important boundaries

CI/merge are not AWS deployment. No direct OpenD provider quota lookup,
runtime candidate add/remove, new quote session, cloud restart, account
access or paid provider request is performed by this PR. The actual
AWS deployment still requires explicit `approve_restart=true` and a
correct `expected_main_sha` per #601; all current trading gates stay closed.

A green observer marker asserts **runtime dry-run safety only**, not
independent proof of subscription quota, provider entitlements, market data
freshness, complete 15m/60m bars, or permission to open Paper/LIVE trades.

`PAPER_AUTO_READY=NO`; `RADAR_ADMISSION=BLOCKED`;
`SOURCE_ARBITER_ADMISSION=BLOCKED`; `LIVE_TRADE=NO`.

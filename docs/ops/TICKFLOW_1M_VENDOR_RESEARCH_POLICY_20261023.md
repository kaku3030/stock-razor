# Explicit one-minute vendor precision research policy

The October13 supplier reply defines non-mutating OHLC consistency within
1e-5 CNY; October20 confirms1m/5m label/successor/revision behavior. These
contracts do not establish strict OHLC or immutable finality. The eight-ULP
subset in PR999 did not resolve all live gaps (audit39911919852).

This is an explicit research eligibility change, not a repair of source prices.
The isolated1m builder opts into vendor_precision_research=True and writes
precision_policy=VENDOR_FLOAT_RESEARCH_ONLY. The session-progress reader
requires that policy for broader1m vendor-tolerated rows. Legacy/default
normalization retains the previous strict/binary subset. Current-day
historical-only reads still reject broader precision before the post-close
window. Unknown policy values fail closed.

Unchanged: original price values, <=1e-5 absolute bound, each ETF price near
its0.001 lattice with valid lattice shape,90-second grace, all due labels,
numeric/amount/volume checks, partial status, UNPROVEN currentness,
NOT_VERIFIED finality, record_only and BLOCKED source/Radar/live admission.
Never present PASS_RESEARCH_ONLY as strict/live trading acceptance.

Windows uses an explicit --vendor-precision-research option for research
coverage counters. Its strict status remains unchanged. Windows offline
still means dual-end parity NOT_VERIFIED.

Validation:146 adjacent tests pass, including publish-grace/negative amount
regressions. Exact deployed20frame acceptance remains independently
required. Rollback: revert and redeploy prior worker/MCP; legacy rows remain
readable under their previous precision policy.

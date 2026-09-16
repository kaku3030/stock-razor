# Live Feed Reliability V0.1 — Permanent Adversarial Coverage Audit

Status: AUDIT / GOVERNANCE ASSET. This document does not alter the frozen 50-case contract.

Purpose: prevent false-green reporting while Slice 1 is intentionally incomplete. A case is **not** considered fully covered merely because `LifecycleState.LIVE` is currently structurally unreachable.

## Status vocabulary

- `ENFORCED+TESTED` — the relevant invariant is implemented on the audited code line and has focused regression coverage on main.
- `VALIDATING-DRAFT` — a concrete repair/test exists in a Draft Harvest PR and the exact PR head has passed its own automated validation, but the repair is not merged to main.
- `ADAPTED-PENDING-VALIDATION` — a concrete repair/test exists in a Draft Harvest PR but has not yet passed its own reproducible validation.
- `STRUCTURAL-ONLY` — current architecture prevents the forbidden outcome incidentally/structurally, but the case's full semantics are not implemented.
- `PARTIAL` — some required identity/control behavior exists, but later recovery/reconciliation semantics remain absent.
- `PROVIDER-EVIDENCE` — provider semantics have empirical/source evidence, but controller behavior is not yet implemented.
- `DEFERRED-BY-FROZEN-SCOPE` — requires a capability explicitly deferred beyond Slice 1 (Currentness, Continuity, RecoveryCandidate, entitlement, ClockTrust, cache trust, session semantics, etc.).

No `VALIDATING-DRAFT`, `ADAPTED-PENDING-VALIDATION`, `STRUCTURAL-ONLY`, `PARTIAL`, `PROVIDER-EVIDENCE`, or `DEFERRED-BY-FROZEN-SCOPE` row may be reported as merged/current-main enforcement.

## Coverage matrix

| Case | Theme | Slice-1 status | Current evidence / next requirement |
|---:|---|---|---|
| 1 | Connected transport, subscription failed | STRUCTURAL-ONLY | CONNECTED cannot promote LIVE because LIVE is unreachable; real subscription qualification is future work. |
| 2 | `subscribe()` returns success | STRUCTURAL-ONLY + PROVIDER-EVIDENCE | Futu RET_OK is empirically administrative only; controller has no success→LIVE path. Full control/data-plane qualification remains future work. |
| 3 | Provider ACK but no data | STRUCTURAL-ONLY | No ACK→LIVE path exists; future control-plane attribution and data-plane qualification still required. |
| 4 | Reconnect without replaying desired subscriptions | STRUCTURAL-ONLY | Reconnect can reach CONNECTED but not LIVE. Desired-vs-provider reconciliation is not implemented. |
| 5 | Administrative resubscribe success, no qualified progress | STRUCTURAL-ONLY | No LIVE promotion exists. Currentness/Continuity qualification remains deferred. |
| 6 | Old-generation callback after newer generation | ENFORCED+TESTED | PR #30's runtime/provider/generation relevance gate is merged on main with focused regression coverage. Draft PR #32 adds independently validated Hypothesis stress coverage for stale-identity sequences, but that extra property-based tooling is not required to claim the production invariant is enforced on main. |
| 7 | QUOTE healthy, required 1M bar stalled | DEFERRED-BY-FROZEN-SCOPE | Requires per-stream liveness/dependency and final health aggregation. |
| 8 | Fresh receive time, stuck source progress | DEFERRED-BY-FROZEN-SCOPE | Requires provider ProgressIdentity + Currentness. |
| 9 | Historical SEED fills realtime cache | DEFERRED-BY-FROZEN-SCOPE | Requires cache trust/provenance and live qualification. |
| 10 | Backfill/catch-up arrives through push path | PROVIDER-EVIDENCE + DEFERRED-BY-FROZEN-SCOPE | Futu has no authoritative replay marker observed in tested surface; controller provenance/recovery handling remains future work. |
| 11 | Disconnect with cached data retained | DEFERRED-BY-FROZEN-SCOPE | Lifecycle disconnect exists; cache-trust revocation is explicitly not implemented. |
| 12 | Partial stream/symbol recovery | DEFERRED-BY-FROZEN-SCOPE | Requires per-stream/symbol health and final aggregation policy. |
| 13 | Realtime entitlement revoked | DEFERRED-BY-FROZEN-SCOPE | Entitlement qualification/revocation is explicitly not implemented. |
| 14 | Transient retry count reaches 50 | STRUCTURAL-ONLY | Slice 1 does not classify by retry count; final recovery policy is not implemented. |
| 15 | Unclassifiable provider error | PARTIAL | Current ERROR path keeps/sets `FailureClass.UNKNOWN`; provider-specific classification policy remains incomplete. |
| 16 | Slow local wall-clock drift | DEFERRED-BY-FROZEN-SCOPE | Requires ClockTrust and external synchronization evidence. |
| 17 | NTP wall-clock jump | DEFERRED-BY-FROZEN-SCOPE | Requires monotonic timeout model + ClockTrust reassessment. |
| 18 | Lunch break / expected silence | DEFERRED-BY-FROZEN-SCOPE | Requires session/trading-expectation input. |
| 19 | Legitimate zero-trade silence | DEFERRED-BY-FROZEN-SCOPE | Requires trading expectation and provider cadence semantics. |
| 20 | Shutdown disconnect/reconnect race | ENFORCED+TESTED | STOP is writer-serialized; post-stop CONNECTED is ignored; post-stop DISCONNECTED resolves cleanly; focused tests exist on main. |
| 21 | Catch-up newer than old watermark but not current | DEFERRED-BY-FROZEN-SCOPE | Requires CurrentnessBoundary. |
| 22 | Duplicate last pre-loss event | DEFERRED-BY-FROZEN-SCOPE | Requires ProgressIdentity comparator and recovery candidate. |
| 23 | Same progress identity, changed payload correction | DEFERRED-BY-FROZEN-SCOPE | Requires correction-vs-progress semantics and Continuity. |
| 24 | DELAYED/UNKNOWN entitlement with fresh timestamps | DEFERRED-BY-FROZEN-SCOPE | DeliveryMode exists as a type; entitlement qualification and LIVE gating are not implemented. |
| 25 | One stream silently revoked | DEFERRED-BY-FROZEN-SCOPE | Requires per-stream control/data-plane health. |
| 26 | One-symbol permission rejection | DEFERRED-BY-FROZEN-SCOPE | Requires per-symbol failure/health aggregation. |
| 27 | Machine suspend/resume clock discontinuity | DEFERRED-BY-FROZEN-SCOPE | Requires ClockTrust discontinuity handling. |
| 28 | Process restart with stale persisted trust | PARTIAL | `runtime_instance_id` exists and merged PR #30 blocks foreign runtime evidence on main; durable cache/trust reset remains future work, so the broader restart-trust case remains only partial. |
| 29 | Desired registry changes during recovery | PARTIAL | Monotonic desired revision and stale-command-result helper exist; full reconciliation/result-application policy is not implemented. |
| 30 | Recovery during CLOSED_SESSION | DEFERRED-BY-FROZEN-SCOPE | Requires session phase + RecoveryCandidate. |
| 31 | Future provider timestamp / clock error | DEFERRED-BY-FROZEN-SCOPE | Requires ClockTrust/currentness evaluation. |
| 32 | Remove then immediate re-add same stream | ENFORCED+TESTED (intent identity only) | Registry preserves epoch memory and increments new incarnation; old-provider-evidence attribution remains future work. |
| 33 | Genuine current bar timestamp earlier than reconnect wall clock | DEFERRED-BY-FROZEN-SCOPE | Requires provider-specific CurrentnessBoundary; raw timestamp comparison is forbidden by design. |
| 34 | Connection-local sequence resets after reconnect | DEFERRED-BY-FROZEN-SCOPE + PROVIDER-EVIDENCE | Requires provider ProgressIdentity comparator; Futu K_1M tested semantics provide limited cross-reconnect evidence, QUOTE remains unresolved. |
| 35 | One current-looking event then silence | DEFERRED-BY-FROZEN-SCOPE | Requires two-phase Currentness + independent Continuity. |
| 36 | REALTIME→DELAYED runtime downgrade | DEFERRED-BY-FROZEN-SCOPE | Requires authoritative entitlement epoch/revocation. |
| 37 | No token; remove/re-add; buffered old incarnation | DEFERRED-BY-FROZEN-SCOPE + PROVIDER-EVIDENCE | Futu unsubscribe is empirically not a drain barrier; attribution policy remains future work. |
| 38 | Catch-up advances but below CurrentnessBoundary | DEFERRED-BY-FROZEN-SCOPE | Requires boundary evaluation. |
| 39 | Currentness then only transport heartbeat | DEFERRED-BY-FROZEN-SCOPE | Requires stream-specific Continuity; ordinary heartbeat cannot substitute. |
| 40 | Per-symbol entitlement differs in same market | DEFERRED-BY-FROZEN-SCOPE | Requires entitlement scope identity. |
| 41 | Unsubscribe success without callback drain | PROVIDER-EVIDENCE | Futu behavior is empirically confirmed; controller incarnation/barrier handling is not yet implemented. |
| 42 | Same-progress correction as Phase 2 | DEFERRED-BY-FROZEN-SCOPE | Requires ProgressIdentity + Continuity. |
| 43 | Entitlement evidence expires | DEFERRED-BY-FROZEN-SCOPE | Requires entitlement evidence freshness/epoch. |
| 44 | Session closes between Phase 1 and 2 | DEFERRED-BY-FROZEN-SCOPE | Requires RecoveryCandidate invalidation + session phase. |
| 45 | Desired stream removed between Phase 1 and 2 | DEFERRED-BY-FROZEN-SCOPE | Requires RecoveryCandidate binding to desired truth. |
| 46 | No-token/no-barrier surviving old subscription | DEFERRED-BY-FROZEN-SCOPE + PROVIDER-EVIDENCE | Requires control-plane uncertainty in parallel with data-plane Currentness/Continuity. |
| 47 | External clock-sync evidence expires | DEFERRED-BY-FROZEN-SCOPE | Requires ClockTrust evidence epoch. |
| 48 | Changed SemanticStreamKey while old stream continues | DEFERRED-BY-FROZEN-SCOPE | Requires strict attribution/binding to semantic identity. |
| 49 | Changed-key callback is unattributable | DEFERRED-BY-FROZEN-SCOPE | Must remain UNVERIFIED/UNPROVABLE; future attribution layer required. |
| 50 | EXPECTED_SILENCE between Phase 1 and 2 | DEFERRED-BY-FROZEN-SCOPE | Requires RecoveryCandidate retention + suspended cadence expectation. |

## Audit conclusions

1. **Do not report 50/50.** Slice 1 intentionally cannot satisfy most semantic recovery cases yet.
2. The strongest completed mainline Slice-1 areas are structural single-writer/immutable publication, shutdown ordering (Case 20), intent incarnation bookkeeping (Case 32), and the merged runtime/provider/generation relevance gate for stale/foreign identity evidence (Case 6).
3. Case 6 was a real enforcement hole despite the frozen contract. PR #30 repairs it and is now merged on main with focused regression coverage, so Case 6 is `ENFORCED+TESTED`. Draft PR #32 independently stress-tests the same stale-identity invariant with Hypothesis and remains additional validated test tooling rather than a prerequisite for main enforcement.
4. Futu provider research already supplies valuable evidence for Cases 2, 10, 34, 37, 41, and 46, but evidence is not controller enforcement.
5. The next permanent-suite conversion targets should be chosen when their owning capability enters implementation. Current priority remains: identity/relevance → provider fault harness → Currentness/Continuity prerequisites, without premature LIVE promotion.

## Promotion rule for this matrix

A row may move to `ENFORCED+TESTED` only when all of the following exist:

- relevant production invariant is implemented on main (not merely incidentally true because a later state is unreachable);
- focused deterministic regression coverage exists;
- where sequence/state explosion matters, adversarial/property coverage exists or is explicitly judged unnecessary;
- provider-dependent assumptions are backed by the Provider Semantic Contract at an appropriate confidence level;
- CI/reproducible validation passes on the exact code being promoted;
- the implementation does not weaken a frozen invariant or silently infer UNKNOWN semantics.

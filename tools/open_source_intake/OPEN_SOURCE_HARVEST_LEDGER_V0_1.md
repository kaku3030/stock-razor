# Open-Source Intake / Harvesting Ledger V0.1

Status: RESEARCH LEDGER — non-production governance/evidence asset.

This ledger records external engineering candidates against the current Radar frozen contracts and invariants. Entry in this file is **not** approval for production use. External maturity, stars, or official-provider status never bypass Defect Audit, Validation, Shadow Live, or the normal Promotion path.

Promotion vocabulary:

`EXTERNAL CANDIDATE -> ADAPTED -> VALIDATING -> SHADOW -> CORE`

Disposition vocabulary:

`DIRECT USE / ADAPT / TEST-REUSE / REJECT`

## Current search map

### Live Feed / Provider Reliability
- live market data feed / streaming quote / realtime feed / market data client
- subscription lifecycle / subscribe / unsubscribe / resubscribe / reconciliation
- reconnect / retry / exponential backoff / jitter / heartbeat / connection state
- provider acknowledgement / subscription ack / push handler / error semantics
- freshness / staleness / currentness / liveness / watchdog
- continuity / sequence gap / duplicate / out-of-order / missing event
- replay / recovery / catch-up / snapshot+delta / backfill
- event time / source time / receive time / observed time / monotonic clock
- idempotency / deduplication / at-least-once / stale result
- deterministic test / fake clock / fault injection / network partition
- blocking SDK call / process isolation / worker kill / bounded shutdown

### Strategy Lab / Validation
- lookahead bias / temporal leakage / recursive indicator bias
- walk-forward / purged cross-validation / embargo / CPCV
- event-driven backtest / fill model / slippage / fee model / brokerage model
- benchmark harness / experiment tracker / reproducibility / replay
- property-based testing / state-machine testing / invariant testing

## Intake batch 2026-09-09

### FutunnOpen/py-futu-api
- URL: https://github.com/FutunnOpen/py-futu-api
- License: Apache-2.0
- Radar problem: Futu/Moomoo provider mechanics, subscription lifecycle, reconnect/resubscribe semantics, provider blocking behavior.
- Initial judgment: official provider SDK and primary semantics evidence source. Do not treat SDK transport recovery as controller recovery or LIVE qualification.
- Harvested evidence:
  - retained/shared subscription visibility is not equivalent to data-plane ownership;
  - autonomous reconnect/resubscribe behavior under tested cut/restore cycles;
  - subscribe return is administrative evidence only;
  - query-subscription visibility does not prove push delivery;
  - successful unsubscribe is not a callback-drain barrier;
  - reconnect resumed tested K_1M/QUOTE push without manual resubscribe;
  - synchronous provider calls can block for operationally unacceptable durations under fault conditions.
- Disposition: `TEST-REUSE / ADAPT`
- Promotion: provider evidence source; no production code promotion implied.

### nautechsystems/nautilus_trader
- URL: https://github.com/nautechsystems/nautilus_trader
- License: LGPL-3.0
- Radar problem: production-grade event-driven market-data lifecycle, reconnect, retained subscription replay, deterministic architecture.
- Initial judgment: high-value architecture and test-method source; direct engine adoption is not justified for Radar's current Python architecture and frozen contracts.
- Harvested methods:
  - transport availability is separate from authentication/subscription/adapter readiness;
  - reconnect invalidates transport/auth state before recovery;
  - re-authentication-before-resubscribe sequencing where required;
  - retained subscription intent/replay;
  - local send success is not authoritative subscription confirmation;
  - stale unsubscribe acknowledgement must not erase a later resubscribe;
  - bounded/idempotent shutdown and explicit reconnect outcomes.
- Radar mapping:
  - preserves `SDK reconnect/resubscribe != controller recovery != LIVE`;
  - candidate recovery chain: `transport_restored -> auth/revalidation -> desired reconciliation -> currentness -> continuity -> recovery qualification -> LIVE`.
- Disposition: `ADAPT / TEST-REUSE`
- Promotion: `EXTERNAL CANDIDATE` methodology source.

### HypothesisWorks/hypothesis
- URL: https://github.com/HypothesisWorks/hypothesis
- License: MPL-2.0.
- Radar problem: adversarial state-machine coverage for LiveFeed invariants and later Strategy Lab contracts.
- Radar adaptation:
  - Draft PR #32: https://github.com/kaku3030/stock-razor/pull/32
  - test-only dependency in CI requirements;
  - generated add/remove/readd/stop/provider-event/stale-identity sequences;
  - permanent structural invariants and shrinking/minimization behavior.
- Validation evidence:
  - exact head `4d27c526dbb93c7430942c3e020ade4e5bf2ebcd`;
  - Research Radar Tests: PASS;
  - repository CI: PASS.
- Disposition: `DIRECT USE` for tests.
- Promotion: `VALIDATING` — automated gates passed; Draft/manual review and merge governance remain separate.

### Shopify/toxiproxy
- URL: https://github.com/Shopify/toxiproxy
- License: MIT
- Radar problem: reproducible fine-grained provider/network failure injection.
- Defect-audit conclusion:
  - Radar already has a stdlib localhost-only `TransportProxy` proving cut/restore/cleanup mechanics;
  - real Futu Wave2 runs already exercised transport loss, reconnect retries, restore, and autonomous resubscribe;
  - basic disconnect/recovery is therefore not a valid reason to add another harness now.
- Potential later value:
  - latency + jitter;
  - directional/asymmetric faults;
  - blackhole/timeout behavior;
  - bandwidth degradation;
  - intermittent/flapping fault composition.
- Cautions:
  - external fault semantics require their own characterization;
  - proxy behavior is not a substitute for Currentness/Continuity/reconciliation/LIVE policy;
  - deterministic cleanup remains a Radar invariant;
  - specialized connect/accept timeout scenarios must not be assumed faithfully modeled.
- Disposition: `TEST-REUSE CANDIDATE / DEFER DIRECT DEPENDENCY`.
- Promotion: `EXTERNAL CANDIDATE`; reopen when a later capability has an explicit fine-grained network-fault acceptance criterion.

### noxdafox/pebble
- URL: https://github.com/noxdafox/pebble
- License: LGPL-3.0
- Radar problem: hard timeout for provider SDK calls that can genuinely hang.
- Harvestable method:
  - process-worker task deadline;
  - timeout terminates the associated worker rather than merely timing out the parent wait;
  - expired worker replacement.
- Defect-audit concern:
  - Futu is a stateful session/callback owner, not a stateless task workload;
  - worker replacement must become explicit Radar worker-generation evidence;
  - child->parent callback IPC and provider-context ownership remain Radar-specific;
  - direct dependency is justified only if it removes enough specialized supervisor code.
- Disposition: `ADAPT / TEST-REUSE CANDIDATE`.
- Promotion: `EXTERNAL CANDIDATE` methodology source.

### joblib/loky
- URL: https://github.com/joblib/loky
- License: BSD-3-Clause
- Radar problem: robust cross-platform process worker lifecycle.
- Harvestable method:
  - safer/reusable process spawning;
  - broken-worker detection and repair;
  - explicit kill-workers lifecycle on executor replacement/shutdown.
- Gap:
  - public worker timeout is primarily idle-worker lifetime, not a per-running-provider-command hard deadline.
- Disposition: `METHOD / REFERENCE`.
- Promotion: `EXTERNAL CANDIDATE` methodology source.

### Python stdlib `ProcessPoolExecutor` (3.11 baseline)
- Radar problem: candidate zero-dependency process isolation.
- Finding: running futures cannot be cancelled; `cancel_futures` affects pending work, not already-running calls. A parent `result(timeout=...)` is therefore not a kill boundary for a stuck SDK call.
- Disposition: `REJECT DIRECT FOR STRICT TIMEOUT` while retaining stdlib multiprocessing primitives as possible building blocks for a specialized supervisor.

### freqtrade/freqtrade
- URL: https://github.com/freqtrade/freqtrade
- License: GPL-3.0
- Radar problem: Strategy Validation Gate, implementation-level temporal leakage and startup-history instability.
- Radar-native adaptation:
  - Draft PR #38: https://github.com/kaku3030/stock-razor/pull/38
  - stdlib-only prefix-invariance audit;
  - separate startup-history sensitivity audit;
  - deterministic replay control prevents nondeterminism from being falsely labeled lookahead;
  - whole-series aggregate and next-row/negative-shift-equivalent adversarial fixtures;
  - fail-closed frozen `lookahead` Hard Gate mapping;
  - no Freqtrade source/dependency and no GPL coupling.
- Validation evidence:
  - exact head `0200a2ad1ff03d385aff649e9a4040b5f1892e82`;
  - Research Radar Tests: PASS;
  - repository CI/backend/Docker gates: PASS.
- Disposition: `TEST-REUSE / METHOD HARVEST`.
- Promotion: `VALIDATING` — current automated gates passed; still Draft and not SHADOW/CORE.

### QuantConnect/Lean
- URL: https://github.com/QuantConnect/Lean
- License: Apache-2.0
- Radar problem: later backtest/execution realism and backtest-live parity.
- Harvestable:
  - brokerage model boundaries;
  - slippage/fee/fill models;
  - asset/broker-specific execution constraints and test matrices.
- Defect Audit focus:
  - avoid importing execution assumptions into Candidate Discovery;
  - preserve Validation/Performance separation;
  - model A-share/ETF constraints independently.
- Disposition: `ADAPT / TEST-REUSE` for future Strategy Lab.
- Promotion: `EXTERNAL CANDIDATE`.

### microsoft/qlib
- URL: https://github.com/microsoft/qlib
- License: MIT
- Radar problem: experiment tracking, reproducible research workflows, rolling evaluation, model artifact lineage.
- Harvestable:
  - Experiment / Recorder abstraction;
  - parameter + artifact logging;
  - rolling workflow patterns;
  - reproducible experiment lineage.
- Defect Audit focus:
  - map experiment identity to Radar claim/evidence/gate versions;
  - preserve Validation/Performance separation;
  - audit custom dataset/feature adapters for temporal leakage.
- Disposition: `ADAPT / TEST-REUSE` for future Benchmark Harness / Model Evaluation Lab.
- Promotion: `EXTERNAL CANDIDATE`.

### vnpy/vnpy
- URL: https://github.com/vnpy/vnpy
- License: MIT
- Radar problem: mature Python gateway boundaries and China-market ecosystem patterns.
- Harvestable:
  - gateway/subscription boundary organization;
  - China-market conventions;
  - gateway/event-engine test patterns after deeper provider-specific review.
- Defect Audit focus:
  - reconnect/resubscribe semantics are gateway-specific;
  - do not import order execution into Radar's current non-auto-trading scope.
- Disposition: `ADAPT / TEST-REUSE` pending deeper audit.
- Promotion: `EXTERNAL CANDIDATE`.

## Concrete outputs already produced by this lane

### LiveFeed Repair R1 — identity relevance

Draft PR: https://github.com/kaku3030/stock-razor/pull/30

- closes the frozen Case-6 runtime/provider/controller-generation relevance gap;
- stale/foreign provider evidence remains diagnostic and cannot mutate lifecycle truth;
- exact head `bfaa193d91ce6dabd7c410691b9a9e5cedd501c5` has PASS on Research Radar Tests and repository CI.

Promotion truth: `VALIDATING`. It is still Draft and not merged, so mainline enforcement must not be claimed.

### LiveFeed generative state-machine testing

Draft PR: https://github.com/kaku3030/stock-razor/pull/32

- Hypothesis is test-only;
- generated state-machine operations cover substantially more orderings than fixed examples;
- exact head automated Research Radar and repository CI gates passed.

Promotion truth: `VALIDATING`.

### LiveFeed network/provider fault audit

See: `LIVE_FEED_NETWORK_FAULT_HARVEST_BATCH_2026_09_09.md`

Produced:

- evidence-backed fault coverage matrix;
- discovery that the later in-repo localhost-only `TransportProxy` already closes the earlier Level-1 fault-injection gap for cut/restore experiments;
- deliberate deferral of Toxiproxy dependency;
- Nautilus recovery-sequencing method harvest;
- identification that production provider-call isolation is a higher-priority proven P0 than finer network fault variety.

### LiveFeed production LANE 3 blocking-executor audit

See: `LIVE_FEED_BLOCKING_EXECUTOR_HARVEST_BATCH_2026_09_09.md`

Produced:

- explicit production executor requirements;
- stdlib `ProcessPoolExecutor` rejection as a direct strict-timeout solution on Python 3.11;
- Pebble and Loky method screening;
- `DESIGN CANDIDATE: PROCESS-ISOLATED SINGLE-PROVIDER SUPERVISOR`;
- separation of controller generation, provider-worker generation, and stream subscription epoch;
- first-terminal-wins timeout/result race rule;
- hard kill/restart/shutdown adversarial test plan.

No runtime dependency or production code was added.

### Data Reliability defect batch

See: `DATA_RELIABILITY_HARVEST_BATCH_2026_09_09.md`

Produced:

- PR #35 — malformed provider numerics become explicit Health evidence instead of adapter crashes; automated gates green;
- PR #36 — stale-good-health revocation for empty/invalid timestamp batches; stacked and still lacks independent CI;
- deliberate non-adoption of heavier schema tooling where it does not solve the proven boundary defect.

### Strategy Validation temporal-leakage batch

See: `STRATEGY_VALIDATION_HARVEST_BATCH_2026_09_09.md`

Produced:

- PR #38 implementation-level temporal leakage audit;
- startup-history sensitivity kept separate from lookahead;
- nondeterminism fail-closed without false causal accusation;
- permanent adversarial cases;
- CI execution-list repair.

Promotion truth: `VALIDATING` with current exact-head automated gates passed.

## Remaining near-term harvesting priority

Completed/advanced items are removed from the top of this queue rather than repeatedly listed as future work.

1. Focused adversarial/design review of the process-isolated single-provider supervisor candidate: IPC, worker-generation identity, exact terminal-result semantics, kill/restart, Windows spawn, shutdown/orphan prevention.
2. Decide whether Pebble materially reduces specialized supervisor risk/code after that design is explicit; do not add dependency before this comparison.
3. After #35 becomes the validated base, independently validate stacked Data R2 / PR #36.
4. Currentness / Continuity / RecoveryCandidate prerequisites; only then reopen fine-grained Toxiproxy-style latency/jitter/asymmetry faults.
5. Lean transaction/fill/slippage test matrix for later Strategy Lab; no production execution scope expansion.
6. Qlib Experiment/Recorder ideas for Benchmark Harness / Model Evaluation Lab lineage.
7. vn.py gateway/provider-specific audit for China-market adapter ideas without importing auto-order scope.

## Governing rule

> Borrow aggressively. Trust nothing. Validate everything.

Harvest increases Radar quality only when external ideas are translated into Radar-native contracts, adversarial evidence, and independently reproducible validation. Code volume, stars, framework breadth, or dependency count are not success metrics.

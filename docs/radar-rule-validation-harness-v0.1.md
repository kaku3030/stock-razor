# Radar Rule Validation Harness V0.1

## Current status

This is the research-only validation machine for Radar rules. It is not a
second Candidate Radar, backtest runtime, provider runtime, portfolio runtime,
or production decision engine.

As of 2026-09-13:

- contract and preflight slice: implemented;
- persistent Experiment Registry and atomic budget reservation: implemented;
- Never-Seen Holdout claim orchestration: pending; the existing OOS
  Consumption Ledger remains the only authority;
- counterfactual execution adapter and result/evidence schema: pending;
- production promotion: not authorized.

The implemented contracts are in
`src/services/strategy_lab/rule_validation_contract.py`; the durable registry
is in `src/repositories/experiment_registry_repo.py`. The contracts freeze the rule,
dataset split, experiment budget, PIT policy, and counterfactual plan into
deterministic fingerprints that an `ExperimentManifest` must bind before a
holdout claim is even eligible.

## Implemented preflight

The preflight runs in this fixed order:

1. `manifest_binding`
2. `dataset_split`
3. `pit_anti_leak`
4. `experiment_budget`
5. `counterfactual_coverage`

Every gate uses `PASS / FAIL / UNKNOWN / NOT_APPLICABLE`. Eligibility requires
all gates to be `PASS`; a profitable metric cannot compensate for any failed
or unknown gate.

### Rule contract

Each rule freezes:

- `rule_id` and `rule_version`;
- hypothesis;
- declared input fields;
- applicable regimes;
- trigger contract;
- expected effect;
- invalidation contract;
- forbidden uses.

`live_order_execution` and `production_promotion` are mandatory forbidden
uses. Removing either makes the contract invalid.

### Split and Never-Seen Holdout

The split contract requires three ordered, non-overlapping half-open temporal
intervals:

`Development -> Validation/OOS -> Never-Seen Holdout`

The contract also binds `dataset_id`, `dataset_version`, and `embargo_bars`.
Construction fails if Development overlaps Validation or Validation overlaps
the Holdout.

Passing this structural gate does not mean the holdout is pristine. The next
write must still be an atomic `claim_if_pristine` through the existing OOS
Consumption Ledger. Preflight has no reset, unconsume, or holdout access path.

### PIT / anti-leak

Every declared rule input needs exactly one PIT evidence record with an
`evidence_id`, `effective_at`, and `available_at`.

- `available_at <= decision_time`: `PASS` for that input;
- missing or unknown temporal evidence: `UNKNOWN` and blocked;
- `available_at > decision_time`: `FAIL` and blocked;
- undeclared fields, duplicate fields, or duplicate evidence IDs: malformed
  input and rejected.

This preflight is additive to the deeper information-dependency,
purge/embargo, walk-forward, and PIT-universe checks already in Strategy Lab.
It does not replace them.

### Experiment budget

The frozen budget has independent hard limits for:

- trial count;
- parameter-set count;
- model-call count;
- human-mutation count.

No dimension compensates for another. Exact-limit reservations pass; any
single exceeded dimension fails the gate.

The pure preflight accepts `ExperimentBudgetUsage` as a snapshot. Execution
authority comes only from `ExperimentRegistryRepository.preflight_and_reserve`:
it re-reads persisted usage, runs preflight, freezes the rule-family budget
policy, and inserts the immutable reservation inside one SQLite `BEGIN
IMMEDIATE` transaction. A failed PIT/preflight or exhausted budget writes no
policy and no registration; a successful reservation is never released or
decremented. Idempotent retries require the same semantic request, including
PIT evidence; a changed request with the same operation ID fails loudly.

The registry owns no holdout interval and writes no OOS event. The existing
OOS Consumption Ledger remains the only authority that can claim or burn
Never-Seen Holdout data.

### Counterfactual plan

Every plan must freeze all five families before results are viewed:

- `with_rule`;
- `without_rule`;
- `shuffled_placebo` with a deterministic seed;
- `delayed_rule` with a positive delay;
- `regime_conditioned` with an explicit regime.

Variant IDs must be unique. Ordering is canonicalized before hashing, so input
order cannot change plan identity.

## OSS-first decision record

The Harvest rule is `DIRECT_REUSE > THIN_ADAPTER > PORT/ADAPT > REIMPLEMENT`.
Implementation reuse never transfers validation or production authority.

| Candidate | License | V0.1 decision | Reason |
| --- | --- | --- | --- |
| [skfolio](https://github.com/skfolio/skfolio) | BSD-3-Clause | `PORT/ADAPT LATER` | Walk-forward and combinatorial purged-CV implementations are useful references, but Stock Razor already has stricter lineage, information-dependency, purge/embargo, and OOS-consumption contracts. |
| [Optuna](https://github.com/optuna/optuna) | MIT | `THIN ADAPTER LATER` | Useful sampler/trial engine after the canonical budget ledger exists; it must not become the authority for experiment identity, human mutations, or holdout consumption. |
| [MLflow](https://github.com/mlflow/mlflow) | Apache-2.0 | `DEFER` | Rich tracking surface, but too much service and dependency scope for the one-week minimum loop. Export can be added after the local registry closes. |
| [vectorbt](https://github.com/polakowo/vectorbt) | Apache-2.0 | `SANDBOX ADAPTER LATER` | Useful for fast signal/portfolio evaluation; cannot own PIT truth, risk authority, lifecycle, or promotion. |
| [Qlib](https://github.com/microsoft/qlib) | MIT | `HARVEST IDEAS ONLY` | Broader research platform than this bounded harness; selectively reuse workflow or fixture ideas, not its runtime boundary. |

No external dependency or copied source was added in the contract/preflight
slice. Existing in-repository Strategy Lab primitives were the smallest and
strongest reuse path.

## WIP cap and next slice

The completed registry slice provides:

- immutable first-seen experiment/contract identity;
- append-only trial, parameter-set, model-call, and human-mutation reservations;
- idempotent operation IDs with semantic fingerprints;
- atomic check-and-reserve under SQLite `BEGIN IMMEDIATE`;
- no reset, decrement, overwrite, or hidden retry path;
- concurrency, replay, PIT, and budget-boundary adversarial tests.

The next and only authorized WIP is a narrow holdout-claim orchestration
adapter: it may join a passed atomic reservation to the existing OOS Ledger,
but may not create another holdout ledger or expose a production path.

## Ownership and synchronization

- `RADAR/QUANT_RESEARCH_MACHINE` owns research validation contracts,
  experiment evidence, counterfactual comparisons, and rule verdicts.
- `RADAR/CONTROL_TOWER` owns promotion and Exit Criteria.
- `RADAR/HARVEST` owns OSS discovery, license/source pinning, and adaptation
  evidence.
- `AI_MONITOR` retains Provider Worker, LiveFeed, Currentness, continuity,
  notification, and production runtime ownership.
- Main Control & Trading Desk receives portfolio-relevant conclusions only
  after Radar promotion; this harness emits no BUY/SELL instruction.

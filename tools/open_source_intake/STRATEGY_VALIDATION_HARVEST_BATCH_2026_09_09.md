# Open-Source Intake — Strategy Validation Harvest Batch 2026-09-09

Status: RESEARCH / DEFECT-AUDIT LEDGER. Non-production.

## Goal

Close the gap between Strategy Lab's **declared temporal causality** and the actual behavior of indicator/signal implementations.

Radar already has foundation controls for:

- aware UTC temporal evidence;
- feature/label/state information dependencies;
- purge/embargo/overlap declarations;
- walk-forward train/selection/evaluation separation;
- OOS consumption governance;
- a permanent timestamp-level lookahead adversarial fixture.

Those controls are necessary but not sufficient. An implementation may still read future rows while reporting plausible timestamps. This batch therefore targets **implementation-level temporal leakage** rather than adding another declaration layer.

## Candidate: freqtrade/freqtrade

- URL: https://github.com/freqtrade/freqtrade
- License: GPL-3.0.
- Radar problem: behavioral detection of lookahead bias and recursive/startup indicator instability.
- Disposition: `TEST-REUSE / METHOD HARVEST`; no source copying and no engine dependency.

### Method harvested: lookahead analysis

Useful pattern:

1. compute a baseline strategy result with the full requested history;
2. rerun strategy/indicator computation with information after a target decision point removed;
3. compare the historical outputs/signals that should already have been fixed at that point;
4. a changed historical output is evidence that later data influenced an earlier computation.

Why this is stronger than a source scanner:

- it tests behavior rather than trying to enumerate suspicious syntax;
- a helper function, library call, global aggregate, future fill, or negative shift can all be detected if they alter an audited historical output;
- it does not claim that absence of a known code pattern proves absence of bias.

Known limitations preserved in Radar governance:

- a PASS is only coverage of the audited cutoffs and executed paths;
- signals/features that never execute at the audited points can still hide defects elsewhere;
- evaluator/runtime failure is not proof of leakage and must be reported as indeterminate;
- comparison policy must be explicit, because floating-point/tolerance choices can otherwise create false positives or false negatives.

### Method harvested: recursive/startup analysis

Useful pattern:

- hold the endpoint constant;
- recompute the same indicator output with different amounts of startup history;
- compare the endpoint output.

Radar adaptation deliberately diagnoses this separately from lookahead. A recursive indicator that has not converged may be unstable without using future data. Conflating the two would produce a false causal accusation and a worse debugging path.

## Radar-native adaptation

Draft PR: https://github.com/kaku3030/stock-razor/pull/38

Branch: `harvest/strategy-temporal-leakage-r1`

### Prefix Invariance Audit

New framework-neutral, stdlib-only audit:

- one evaluator run over full history creates the behavioral baseline;
- explicit cutoffs are audited;
- each cutoff is rerun with the exact prefix ending at that cutoff;
- full-history output at the cutoff is compared with prefix-only output at the same cutoff;
- the final row cannot be used as a vacuous cutoff because it hides no future tail;
- output contract requires one simple finite-scalar snapshot per input row;
- exact comparison is used in V0.1; callers needing tolerance must canonicalize explicitly rather than relying on a hidden Strategy Lab threshold.

Result semantics:

- `PASS`: every requested cutoff was executed and prefix-invariant;
- `LEAKAGE_DETECTED`: at least one audited output changed when its future tail was hidden;
- `INDETERMINATE`: evaluator error, malformed/non-finite output, or incomplete output coverage prevents a trustworthy conclusion.

Frozen Hard Gate adaptation is fail-closed:

- PASS -> `lookahead` gate passes with `implementation_prefix_invariant`;
- leakage -> fails with `implementation_future_dependency_detected`;
- indeterminate -> fails with `implementation_leakage_audit_indeterminate`.

The existing frozen Hard Gate order is unchanged.

### Startup History Sensitivity Audit

Separate report semantics:

- `STABLE`;
- `SENSITIVITY_DETECTED`;
- `INDETERMINATE`.

It is evidence for warmup/recursive diagnosis and is **not automatically converted into a lookahead failure**.

## Permanent adversarial coverage added

The adaptation includes deliberately bad and valid controls for:

1. causal rolling feature -> prefix invariant;
2. whole-series aggregate -> future dependency detected;
3. next-row / negative-shift-equivalent signal -> future dependency detected;
4. missing evaluator outputs -> indeterminate / Hard Gate fail-closed;
5. non-finite output -> indeterminate rather than false PASS;
6. final-row-only audit -> rejected as vacuous;
7. sufficient fixed rolling warmup -> stable across startup lengths;
8. cumulative/start-dependent feature -> startup sensitivity detected separately.

The existing permanent five-case Strategy Lab adversarial suite is also extended so its `lookahead` family proves that implementation-level future access cannot escape merely because declared timestamps look valid.

## CI governance finding

During this harvest, an unrelated but important CI truth issue was found:

- the Research Radar workflow path trigger already matches `tests/test_strategy_lab_*.py`;
- however the actual pytest command manually enumerates each Strategy Lab test file;
- therefore adding a new matching test file without updating the command could trigger a green workflow that never executed the new test.

PR #38 explicitly adds `tests/test_strategy_lab_temporal_leakage.py` to the pytest command. New Strategy Lab validation modules must continue to verify both **workflow trigger coverage** and **test execution coverage**.

## Promotion truth

At creation time PR #38 is `ADAPTED` and Draft.

Promotion to `VALIDATING` requires the newly enumerated focused suite and repository CI to execute successfully on the actual PR head. External project maturity and the quality of the method are not substitutes for Radar-native validation.

## Decision from this batch

Do not import Freqtrade or its GPL implementation into Radar.

Harvest the **verification method**, implement it against Radar's frozen contracts, make failure/indeterminate semantics explicit, retain adversarial controls permanently, and let CI prove that the adapted implementation actually runs.

This is the Open-Source Intake principle in executable form:

> Borrow aggressively. Trust nothing. Validate everything.

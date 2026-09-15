# Open-Source Intake — Data Reliability Harvest Batch 2026-09-09

Status: RESEARCH / DEFECT-AUDIT LEDGER. Non-production.

## Goal

Extend Harvesting beyond LiveFeed into the current Foundation/Data Reliability phase without creating a second quality architecture. External schema/data-quality frameworks are evaluated against Radar's existing `MarketDataAdapter`, `MarketDataHealth`, `ExistingMarketDataAdapter`, and `DataCapabilityService` boundaries first.

## Candidate: unionai-oss/pandera

- URL: https://github.com/unionai-oss/pandera
- Current GitHub license metadata observed on 2026-09-09: MIT.
- Project description: lightweight/flexible statistical data testing and dataframe-schema validation.
- Radar fit: potentially useful later for offline dataset/schema assertions, fixture generation, and research-table validation.
- Current disposition: `REJECT-DIRECT-DEPENDENCY-FOR-NOW / TEST-REUSE-METHODS`.

Reasoning:

1. Radar already has an explicit provider-normalization boundary and deterministic `MarketDataHealth` gate.
2. The defects found in this batch are boundary-semantics bugs, not absence of a dataframe schema library.
3. Adding Pandera now would not by itself solve stale-health publication, provider provenance, timestamp trust, or malformed-value semantics.
4. A new dependency would be justified only if repeated schema drift across multiple datasets produces enough duplicated hand-written checks to outweigh the dependency and dual-semantics cost.

Harvestable without adoption:

- explicit schema contracts for offline datasets;
- lazy/multi-error validation patterns;
- property/statistical checks separated from provider transport logic;
- test organization for dataframe contract violations.

## Great Expectations / GX

The historical `great-expectations/great_expectations` repository endpoint currently redirects. This batch does not promote a specific current GX repository identity without a clean repository-resolution check.

Current disposition: `NO-DIRECT-USE / METHODOLOGY-ONLY PENDING RE-RESOLUTION`.

Reasoning: even if the current project is suitable, GX-style expectation suites are substantially broader than the immediate Radar adapter defects. Do not introduce a heavyweight expectation framework to repair local normalization/health-state invariants.

## Internal defect harvest produced by this batch

### Data R1 — malformed numeric bypassed quality gate

Draft PR: https://github.com/kaku3030/stock-razor/pull/35

Verified code-path defect:

- existing adapter used direct `float(...)` conversion on provider quote/bar values;
- non-empty dirty tokens such as `--`, `N/A`, non-numeric strings, or +/-Inf could fail before `MarketDataHealth` received the evidence;
- daily optional `amount` had the same exception path.

Repair principle:

> Dirty provider evidence must become explicit quality evidence, not an adapter crash and not a silently valid value.

Adapted behavior:

- bounded finite-number coercion at the existing normalization boundary;
- genuine missing values remain missing;
- malformed/non-finite values emit `INVALID_NUMERIC`;
- `INVALID_NUMERIC` is severe in the existing Health Gate and therefore BLOCKED;
- required malformed bar values remain incomplete/`PARTIAL_BAR`;
- no new quality subsystem or external dependency.

Test matrix includes:

- `--`, `N/A`, arbitrary non-number, +Inf, -Inf;
- distinction from genuine missing `None`, blank string, NaN;
- each required OHLCV field independently malformed;
- malformed optional amount;
- negative volume remains severe;
- valid numeric strings normalize without `INVALID_NUMERIC`.

Validation status at latest ledger sync:

- Research Radar focused tests: PASS on PR #35 head.
- Main CI backend shards 1/3, 2/3, 3/3: PASS.
- backend-gate: PASS.
- docker-build: PASS.
- AI governance / change detection: PASS.
- Web/Desktop jobs were correctly skipped by path detection.
- Current promotion truth: automated validation gates observed for this PR head are green; keep Draft/manual-review governance separate from CI status.

### Data R2 — stale good health survived empty/invalid batches

Stacked Draft PR: https://github.com/kaku3030/stock-razor/pull/36
Base: `harvest/market-data-numeric-coercion-r1` / PR #35.

Verified code-path defect:

- `get_bars()` returned immediately for empty frames without refreshing `_last_health`;
- invalid timestamps were silently skipped;
- an empty/all-invalid later batch could therefore inherit a previous NORMAL/healthy state;
- a mixed valid+invalid-timestamp batch could silently discard evidence while returning apparently actionable bars.

Repair principle:

> Missing or discarded provider rows cannot coexist with inherited actionable health.

Adapted behavior:

- empty batch publishes `MISSING_BAR` health and revokes prior good state;
- all-invalid timestamp batch publishes `MISSING_BAR + TIMESTAMP_MISMATCH`;
- mixed valid/invalid timestamp batches mark surviving bars with batch `TIMESTAMP_MISMATCH` evidence;
- existing severe `TIMESTAMP_MISMATCH` policy blocks downstream actionable permission.

Validation status at latest ledger sync:

- `ADAPTED` only.
- PR #36 head currently has zero independent check-runs.
- Reason: it is stacked on PR #35 and its pull-request base is not `main`; current workflows are configured to trigger pull-request validation against `main`.
- Therefore PR #35's green checks must **not** be inherited or described as validation of PR #36.
- Required next gate: after #35 lands (or #36 is otherwise retargeted onto an equivalent validated base), run #36 independently before promotion.

## Evidence-governance repair produced in parallel

Draft PR: https://github.com/kaku3030/stock-razor/pull/34

Problem: Live Feed Contract Section 21 carried a pre-Wave-2 provider-evidence snapshot while its own named authoritative Futu evidence registry had newer closed-Wave-2 results.

Repair: non-normative provider-evidence status overlay, preserving frozen architecture while synchronizing F15/F17/F18/AUTO_RESUBSCRIBE/F04 status.

## Decision from this batch

Do **not** add Pandera or a GX-style framework merely because they are mature data-quality projects.

Current higher-quality path is:

1. enforce provider normalization at the adapter boundary;
2. encode dirty/missing/timestamp semantics into Radar's existing Health Gate;
3. add focused and adversarial regression tests;
4. only introduce external schema tooling later when repeated offline dataset-contract duplication proves a concrete need.

This is deliberate `200%` execution: more validation depth and stronger invariants, not more dependencies.

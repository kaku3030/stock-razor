# MCI-E06 — Agent Read-Set / Token Benchmark

**Initiative:** Minimal Core V0.3  
**Mode:** research / measurement only  
**Production behavior change:** none

## 1. Purpose

Measure whether a simplification actually reduces the amount of repository context an engineering agent must load to make a correct governed change.

This benchmark exists because LOC reduction can be fake. Moving the same semantics across more wrappers may reduce a file while increasing total read-set and tokens.

## 2. Primary metrics

For each task, record before/after:

- `files_opened_to_understand`
- `files_opened_to_modify`
- `bytes_read`
- `estimated_or_measured_input_tokens`
- `semantic_owners_touched`
- `private_attributes_crossed`
- `provider_specific_contracts_seen`
- `decision_branches_relevant`
- `tests_needed_for_confidence`
- `time_to_identify_authoritative_owner`
- `wrong-path/reopen count`

Token count must be measured with the same tokenizer/tooling when comparing alternatives. Do not convert byte reduction directly into a token-saving claim.

## 3. Baseline structural evidence

Current repository metadata shows several large semantic surfaces:

- `realtime_monitor/server.py`: ~304 KB;
- `data_provider/base.py`: ~207 KB;
- `data_provider/akshare_fetcher.py`: ~104 KB;
- `data_provider/efinance_fetcher.py`: ~56 KB;
- `src/services/data_capability_service.py`: ~46 KB.

These byte sizes are not quality scores. They only establish that a task which requires broad reading of these files can become expensive for humans and agents.

## 4. Benchmark tasks

### E06-T1 — Currentness bug

Prompt:

> A 15m/1h observation during lunch break or immediately after market close is being marked stale incorrectly. Find the authoritative logic and propose the smallest safe correction without changing production ownership.

Record whether the agent must inspect unrelated sections of `realtime_monitor/server.py`, provider code, calendar logic, prompts, and notification code before locating the governing seam.

Target after E01-style pure-core extraction: the agent should be able to understand semantic currentness behavior from a small core + fixtures, with the runtime shell needed only for integration verification.

### E06-T2 — Add/change one provider capability

Prompt:

> Change one provider's supported market/dataset capability or priority and update all authoritative diagnostics without changing runtime routing unintentionally.

Current likely read-set includes:

- provider fetcher;
- `data_provider/base.py` manager/routing facts;
- `src/services/data_capability_service.py` provider registry/maps;
- `data_provider/__init__.py` package/provider documentation;
- config definition for credential/routing changes;
- relevant tests.

E05 Shadow target: determine whether a manager-owned read-only capability/routing snapshot reduces this read-set.

### E06-T3 — Retry policy audit

Prompt:

> Determine whether a transient timeout should be retried, failed over, cooled down, or returned immediately for Efinance, AkShare, Futu, Longbridge and fundamental fetches.

The benchmark must detect whether the agent confuses:

- retry;
- provider/source failover;
- circuit breaker;
- cooldown;
- timeout budget;
- fail-open;
- semantic no-retry conditions.

E03 target: a small failure taxonomy/policy vocabulary should reduce reopen/reasoning cost while preserving provider-specific policies.

### E06-T4 — Notification delivery failure

Prompt:

> Discord primary delivery fails. Determine whether retry or email fallback is legal and what state/result must be emitted.

A successful minimal-core design should make the governed single-attempt/fallback rule discoverable without reading unrelated AI, portfolio or market-data code.

### E06-T5 — Add an HK symbol form

Prompt:

> Support one additional canonical HK symbol input form without causing A-share/ETF collision and without leaking a provider wire format into generic market classification.

Measure how many separate implementations of HK classification/conversion must be inspected. E05 predicts a benefit from one canonical classification owner plus provider-local wire conversion.

## 5. Benchmark protocol

For each task:

1. start from a fresh agent context;
2. provide only repository + task + governing project rules;
3. record every repository file read before the agent can state the authoritative owner;
4. record every file reopened after discovering a hidden dependency;
5. produce a proposed patch plan, but do not merge;
6. score correctness against a known answer key;
7. repeat after a Shadow architecture prototype using the same model/settings;
8. compare medians across repeated runs when stochastic agents are used.

### 5.1 Baseline recording infrastructure

The repository has no equivalent E06 recorder; this is `SIBLING_CHECKED_NO_EQUIVALENT`.
Use `scripts/e06_benchmark.py` to validate one JSON object per JSONL row. It records
Layer A/B/C independently, all primary metrics (including `wrong_path_count` and
`reopen_count`), a contamination flag, and the correctness-gate result. The tokenizer
is the existing `tiktoken` dependency with fixed `cl100k_base` encoding; no byte-based
token estimate is permitted. The self-test is not an official sample. The validator
fails closed: `correctness_gate.result=PASS` requires explicit `PASS` for all seven
protected contracts (`production_owner_correct`, `unknown_preserved`,
`no_unauthorized_second_runtime_or_source`, `retry_vs_fallback_semantics_correct`,
`currentness_calendar_not_delegated_to_llm`,
`notification_single_attempt_or_fallback_legality_preserved`, and
`required_tests_or_replay_named`). Missing, `None`, `UNKNOWN`, or `FAIL` is never PASS.

Contaminated/current-chat/migration samples are emitted as
`official_status=CONTAMINATED` and cannot be official baseline candidates. A fresh
sample starts as `PENDING_FRESH_CONTEXT`; local validation never emits or accepts
`ELIGIBLE`. Official eligibility and promotion are an external step outside this
harness, so mutating a current-chat row or supplying a fresh-looking row cannot
grant local authority. All seven explicit contract evaluations must pass for a
claimed correctness PASS, while local validation still keeps the sample pending
fresh context. E06-T5 may reuse this recorder for E12 evidence; do not create a
second E12 harness.

## 6. Correctness gate

Read-set savings count only if all are true:

- production owner identified correctly;
- `UNKNOWN` and indeterminate states preserved;
- no unauthorized second runtime/source of truth proposed;
- provider retry vs fallback semantics identified correctly;
- currentness/calendar semantics not delegated to LLM judgment;
- notification single-attempt rule preserved;
- required tests/replay named correctly.

A smaller context that produces a wrong architecture scores worse than a large context.

## 7. Token benchmark layers

Measure three layers separately:

### Layer A — repository read-set

Tokens from source/docs required to solve the task.

### Layer B — tool-output projection

Tokens from GitHub search/list/test/log outputs. This is where Headroom-style compression may help after protected fields are defined.

### Layer C — conversation/history

Tokens from prior design discussion needed to continue work. Prefer durable repo docs/pointers over replaying long chat history.

Do not combine the layers into one headline number until all three are measured.

## 8. Initial hypotheses, not claims

- Pure Currentness core + fixtures should materially reduce E06-T1 read-set.
- Provider capability snapshot may reduce E06-T2 read-set by eliminating parallel provider registry knowledge.
- Explicit failure taxonomy may reduce E06-T3 reasoning/reopen cost.
- Headroom can reduce Layer B, but should be evaluated only after structural read-set improvements so it does not hide architecture debt.

No percentage saving is claimed in this document.

## 9. Promotion criteria

A simplification is considered agent-context-positive when, across the benchmark tasks it targets:

- correctness stays at 100% on protected governance questions;
- median files/bytes/tokens read decrease; reductions from correctness-failing,
  contaminated, single-run, bytes-only, or LOC-only samples are not savings evidence;
- authoritative owner is identified earlier;
- reopen count does not increase;
- tests required for confidence do not increase because semantics became hidden;
- the change does not add a generic framework whose own read-set offsets the savings.

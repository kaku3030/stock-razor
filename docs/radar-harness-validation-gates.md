# Radar Harness V0.1 — Validation Gate Runbook

This runbook is research-only. A captured artifact is never a production approval.

## Required order

1. Verify capture manifest status is `CAPTURED_NOT_APPROVED`.
2. Verify PIT timestamps and raw hash before any feature or label computation.
3. Run development and validation replay with fixed rule version and cost assumptions.
4. Lock the Never-Seen Holdout ID before reading its metrics.
5. Run counterfactuals: `without_rule`, `with_rule`, `delayed_rule`, `shuffled_placebo`, and `regime_conditioned`.
6. Record UNKNOWN/FAIL gates explicitly; neither may be converted into a promotion.
7. Store the result artifact and lineage hash in the experiment registry.

## Promotion boundary

Only `ROBUST` evidence may become `SHADOW_ELIGIBLE`. This Harness does not authorize production promotion, live orders, or portfolio changes.

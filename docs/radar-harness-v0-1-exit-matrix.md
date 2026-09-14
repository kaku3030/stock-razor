# Radar Harness V0.1 Exit Matrix

| Item | Engineering status | Evidence / blocker |
|---|---|---|
| PIT-approved dataset | READY, not approved | `approve_research_capture.py` requires an operator approver/reason |
| Never-Seen Holdout replay | READY | Holdout ID is required and protected; run only after PIT approval |
| Robustness experiments | READY | Replay/counterfactual runners are wired; execute on approved data |
| Rule adjudication | READY | Results must be classified ROBUST/INCONCLUSIVE/REJECTED after evidence |
| Merge / production promotion | LOCKED | PR merge and production promotion require explicit authorization |

## Close-out sequence

1. Operator reviews provenance and executes the PIT approval command.
2. Run the protected holdout replay and counterfactual suite.
3. Run robustness checks with fixed costs, slippage, and delay assumptions.
4. Record rule adjudication and lineage in the experiment registry.
5. Obtain explicit merge authorization; production promotion remains a separate decision.

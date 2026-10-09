# Routine Development Governance

Routine Stock Razor development does not require manual Code Owner approval.

The merge gate for ordinary changes is the active GitHub ruleset on `main`:

- required checks: `backend-gate` and `focused-tests`;
- branch protection and non-fast-forward safeguards remain enforced;
- Code Owner review is informational and is not a required merge condition.

The repository's `pr-review` workflow is advisory. It may provide metadata,
security, labeling, or AI review assistance, but it must not be treated as a
manual approval gate or as evidence of runtime, provider, Radar, deployment,
or trading authorization.

This policy does not remove domain-specific evidence gates. Research/PIT
approval, provider entitlement, deployment authorization, Radar admission, and
trading authorization remain separate decisions and must stay fail-closed when
their evidence is missing.

When this policy changes, verify the live GitHub ruleset before changing local
documentation or workflow wording. Do not bypass an enforced check or branch
protection rule.

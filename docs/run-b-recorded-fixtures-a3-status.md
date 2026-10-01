# Run B Recorded Market Fixtures A3 — Status

Authoritative implementation branch: `harvest/run-b-recorded-fixtures-a3`.

This A3 slice is DATA/TEST research infrastructure for **PUBLIC-SOURCE RECORDED-FIXTURE HISTORICAL-REPRODUCIBILITY**. Its concrete `RecordedMarketFixture` / `RecordedAuthoritySnapshot` implementation is the immutable GitHub/public-source licensed-CSV specialization: canonical repository/path/ref/line provenance, GitHub source identity, and pinned source/license commit/blob evidence.

Current head lineage starts from accepted A2 replay substrate `ae044adf4acb5bbb1174c810bc7c51f0d37697a4`.

## Frozen boundaries
- Embedded capture-time authority snapshot + canonical digest for the GitHub/public-source fixture specialization.
- Distinct timezone-aware `available_at` and `observed_at`.
- Immutable GitHub source commit/blob and license provenance.
- Current authority is diagnostic-only; drift cannot rewrite historical truth.
- Missing/tampered/unresolvable authority evidence fails closed.
- Materialized recorded events retain authority digest/reference lineage.
- Replay remains side-effect free and does not promote example pattern thresholds.

## Provider/API separation
Generic provider/API-recorded historical evidence is broader than this A3 concrete class. Provider/API captures MUST NOT be forced into A3 by fabricating `github://` identity, repository line ranges, GitHub content endpoints, source commit/blob, or license provenance. The separate A4b V0.2 provider-recorded fixture domain is the downstream path for verified provider raw capture + capture-time provider-authority evidence + normalization lineage.

## Non-scope
No independent provider accuracy, provider/API capture authority, Currentness, Continuity, routing/fallback, SHADOW_ACTIVE, CORE, LIVE, notifications, strategy execution, AI-trader, broker or BUY/SELL authority.

Any exact-head CI/review evidence must bind the current A3 head; older-head results are Historical Record only.

# TickFlow automatic scan baseline and failure evidence

AUTO_200 reserves the shared data_provider.cn_tickflow_research_cache.SYMBOLS
baseline before adding active CN stock candidates from stocks.index.json.
The total remains capped at MAX_SCAN_SYMBOLS (200), with deduplication.
The baseline is a research configuration, not a declaration of actual holdings.
Explicit operator symbol lists retain their existing override behavior.

The pinned installer resolves baseline constants from its exact repository
revision using PYTHONPATH; it does not query a provider to construct the list.
The existing #868 active-flag filter and bounded 30-second large-scan SDK
request timeout are retained, with max_retries=0 and unchanged outer backoff.

Batch requests happen before per-symbol normalization. Their failures now carry
fixed BATCH_1M_FETCH / BATCH_5M_FETCH / BATCH_15M_FETCH / BATCH_60M_FETCH /
BATCH_1D_FETCH stages. Locally detected invalid batch shapes or missing symbol
keys project only BATCH_SHAPE_INVALID or BATCH_SYMBOL_MISSING; unknown provider
text is never exported. The readonly auditor accepts the same five periods and
bounded S0..S199 per-symbol stages, preserving errors outside the old four-symbol
scope. Invalid and secret-bearing stage values remain UNKNOWN.

This fixes baseline loss and missing failure attribution. It does not establish
the cause of a previously emitted UNKNOWN failure, repair provider data, mark
bars final, increase request/retry limits, deploy code or qualify any admission.
Cloud collection and due-grid/finality acceptance require a separate exact-version
run. Keep SOURCE_ARBITER_ADMISSION=BLOCKED, RADAR_ADMISSION=BLOCKED and LIVE_TRADE=NO.

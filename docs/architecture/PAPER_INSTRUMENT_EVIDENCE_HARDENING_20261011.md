# US SIM instrument-bound evidence (2026-10-11)

**Status: offline evidence validation only. No order API use.**

This change tightens the already merged #583 independent provider-evidence
policy. Position baselines and realized-fill observations must include a
syntactically valid US symbol, and the before position, after position, and
independently observed fill must all belong to the *same* symbol. A matching
numerical quantity and cash delta is **not** independent proof when the
instrument differs. Missing symbol evidence fails closed.

The data classes retain a backward-compatible optional symbol default, but
an omitted/invalid symbol no longer produces PASS. The provider must bind a
specific account, session generation, symbol, provenance ID and independent
fill to real read-only observations, not synthetic fixtures.

The official OpenD US SIM `deal_list_query` limitation is unchanged.
Existing four Windows LONG positions, cloud-vs-Windows account identity,
provider-external fill proof, order idempotency and recovery are NOT verified.
A first actual SIMULATE order still needs **separate explicit approval**.

`SOURCE_ARBITER_ADMISSION=BLOCKED`; `RADAR_ADMISSION=BLOCKED`;
`PAPER_AUTO_READY=NO`; `LIVE_TRADE=NO`.

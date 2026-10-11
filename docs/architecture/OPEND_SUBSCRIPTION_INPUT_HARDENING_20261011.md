# OpenD candidate subscription input validation (2026-10-11)

**Status: offline contract only. No OpenD mutation/deployment.**

This change strengthens the already merged #582 singleton-owner subscription
manager's stream-key safety boundary. US candidate symbols must now match a bounded
and unambiguous US symbol grammar, blocking empty, padded, injected or malformed
identifiers **before** a provider adapter can mutate subscriptions. An invalid
clock supplied by the owner also fails closed. The existing quota, subscription
delta, recovery-token, warm start and single-adapter-owner policies are unchanged.

Still unknown in AWS: deployed manager revision; source of quota observation;
actual package subscription cap; owner-to-manager integration; live add/remove;
recovery; history warm start; Radar candidate integration. No realtime data
admission and no trade admission follows from the offline tests.

`SOURCE_ARBITER_ADMISSION=BLOCKED`; `RADAR_ADMISSION=BLOCKED`;
`PAPER_AUTO_READY=NO`; `LIVE_TRADE=NO`.

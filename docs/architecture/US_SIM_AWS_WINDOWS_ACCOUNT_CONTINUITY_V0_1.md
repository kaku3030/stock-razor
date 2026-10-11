# US SIM cross-host account identity review, privacy-safe and read-only

The operator confirmed the four existing positions originated from prior
manual SIMULATE trades. #588 quarantines them from strategy performance.
This pure comparator requires independent fresh Windows and AWS readback
observations, exact raw account ID equality inside memory, US SIMULATE mode,
session authentication, bounded times and equivalent normalized positions.

Result MATCHED_FOR_REVIEW is never a fill receipt, does not reconstruct past
execution, and does not grant a first SIM order. Windows and AWS generations
can legitimately differ because they are distinct sessions; the comparator
checks that both are identifiable and fresh without treating generation
strings as interchangeable broker identifiers.

No live cloud readback was performed by this PR. Do not publish raw account
IDs, broker rows, private holdings/P&L, deterministic raw-ID hashes or
screenshots to GitHub/CI. Use a controlled private transport and report only
sanitized reason codes and position counts; ensure no credentials in logs.

PAPER_AUTO_READY=NO; RADAR_ADMISSION=BLOCKED;
SOURCE_ARBITER_ADMISSION=BLOCKED; LIVE_TRADE=NO.

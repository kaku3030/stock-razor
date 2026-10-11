# Private Windows / AWS US SIM readback review (2026-10-12)

The existing four US SIMULATE holdings were previously opened manually and
are **legacy holdings**, not new STOCK RAZOR strategy transactions or verified
independent fills. #588 and #593 quarantine these holdings and define a
pure cross-host comparator.

This follow-up provides a **local-only, transport-free** wrapper which reads
two operator-supplied private JSON files and emits a sanitized status, reason,
position count and identity-equality flags. It does not echo account IDs,
symbols, quantities, balances, P&L, readback timestamps, account generations,
raw input or hashes of private IDs.

## Private input contract

Never commit or upload these inputs to the repository, CI/Actions, GitHub
issues, PR comments or public logs. Store privately outside the repository
with restricted permissions. Collect two authenticated broker readbacks within
120 seconds of each other and review promptly.

Each JSON uses schema stock_razor_private_us_sim_readback_v0_1 and has exactly
these keys: schema, account_id (numeric ASCII text), source
(WINDOWS_LOCAL_OPEND / AWS_OPEND_SSM), account_generation, observed_at_utc
(timezone-aware ISO8601), account_mode (SIMULATE), market (US),
authenticated (boolean), positions (array of objects each containing symbol,
side, quantity). Quantity must be a decimal string; each symbol+side
combination must be unique. The wrapper does not independently verify source
provenance: obtaining the inputs from genuine independent readbacks is an
operator-controlled step, NOT proven by merely labeling JSON files.

Run privately:

    python scripts/verify_sim_cross_host_private.py --windows-file <private-path> --aws-file <private-path>

MATCHED_FOR_REVIEW is **not** evidence of any realized fill, broker-origin
provenance, Paper trading readiness, or clean strategy P&L. Mismatches,
stale/invalid inputs and uncertain identity fail closed. No broker network
calls, mutations, storage writes, payment, deployment or trade orders occur.

A first real US SIMULATE order requires separate explicit authorization;
independent fill evidence is still unresolved.

PAPER_AUTO_READY=NO; RADAR_ADMISSION=BLOCKED;
SOURCE_ARBITER_ADMISSION=BLOCKED; LIVE_TRADE=NO.

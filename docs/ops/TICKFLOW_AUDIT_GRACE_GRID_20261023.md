# TickFlow sanitized audit due-grid correction

The audit previously marked legal received labels within the 90-second grace
as INVALID_TODAY_LABEL_GRID. The source reader could correctly pass the same
frame. Audit run 39904715272 exposed this mismatch for 159363 1m.

The audit now validates current-day received labels against the session grid,
current clock and duplicates, then computes coverage against the smaller due
set. Newer legal rows do not fill earlier gaps. Future, off-grid and duplicate
rows remain invalid. This only changes sanitized diagnostics; no collector,
OHLC tolerance, source finality, currentness or admission policy changes.

Base f4d6373 reproduces two failures; the fix passes 125 adjacent tests.
The merged workflow must be observed independently before runtime verification.
Rollback: revert the audit correction and accompanying regression/registry entry.

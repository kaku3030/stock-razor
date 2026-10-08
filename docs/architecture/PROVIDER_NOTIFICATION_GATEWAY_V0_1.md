# STOCK RAZOR Provider Notification Gateway V0.1

Status: MAINLINE CI CANDIDATE / RESEARCH-ONLY  
Governance: `RADAR_ADMISSION=BLOCKED`, `LIVE_TRADE=NO`

## Objective

Bridge typed Provider Alert Engine transitions into the repository's existing
notification stack without creating a second sender/routing system.

At runtime the gateway accepts any object implementing the existing
`send_with_results(...)` surface, including `NotificationService`.

## Existing notification stack reused

Every transition is dispatched with:

- `route_type="alert"`;
- mapped severity `info/warning/critical`;
- a stable dedup key;
- a stable cooldown key;
- a small structured payload containing only lifecycle alert metadata.

Channel routing, quiet hours, minimum severity, dedup TTL, cooldown, Markdown
rendering, context delivery, static channels, and per-channel diagnostics remain
owned by the existing notification subsystem.

## Recovery notification rule

`RESOLVED` transitions are sent at `info` severity even if the incident was
originally critical.

OPEN, UPDATED, and RESOLVED use separate cooldown buckets. This prevents an
incident's OPEN cooldown from suppressing the recovery notification.

## Safety boundary

The gateway receives only a typed `ProviderAlertTransition`; it never receives
raw provider HTTP responses, credentials, or API keys.

Dispatch exceptions are converted to a sanitized error code containing only the
exception class name. Exception text is not retained.

Notification success or failure cannot mutate:

- Provider Lifecycle state;
- Data Admission;
- Radar Admission;
- LIVE_TRADE;
- provider fallback selection;
- billing or plan state.

## Non-goals

V0.1 does not:

- create notification channels;
- choose provider fallbacks;
- retry delivery itself;
- persist cross-process dedup state;
- make trading decisions;
- authorize Paper or live execution.

## Stacked-development note

This implementation is developed above Provider Alert Engine V0.1. It is not
eligible to merge only when the final diff is based on current canonical `main`,
required CI/tests are fresh and green on the exact head, and no safety gate is
failed or UNKNOWN. Human approval and Code Owner approval are not merge gates.

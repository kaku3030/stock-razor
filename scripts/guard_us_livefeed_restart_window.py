"""Conservative no-RTH US LiveFeed restart guard (source/CI-side only).

A successful check means only that the clock is outside a conservative
US weekday safety window. It is NEVER a trading or market-data qualification.
The EC2 installer also independently checks the clock immediately before any
existing service/repository mutation, since GitHub checks can race with RTH.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")
WINDOW_START = time(9, 0)
WINDOW_END = time(16, 30)


def classify_us_livefeed_restart_window(instant: datetime) -> str:
    """Block US weekdays 09:00–16:30 ET (DST-safe); reject invalid clocks."""
    if (
        not isinstance(instant, datetime)
        or instant.tzinfo is None
        or instant.utcoffset() is None
    ):
        return "CLOCK_UNKNOWN_BLOCKED"
    try:
        local = instant.astimezone(EASTERN)
    except (ValueError, OverflowError, OSError):
        return "CLOCK_UNKNOWN_BLOCKED"
    if local.weekday() < 5 and WINDOW_START <= local.time().replace(tzinfo=None) < WINDOW_END:
        return "US_SESSION_SAFETY_WINDOW_BLOCKED"
    return "SAFE_OFF_WINDOW"


def main() -> int:
    try:
        verdict = classify_us_livefeed_restart_window(datetime.now(timezone.utc))
    except Exception:
        verdict = "CLOCK_UNKNOWN_BLOCKED"
    print("US_LIVEFEED_RESTART_TIME=" + verdict)
    return 0 if verdict == "SAFE_OFF_WINDOW" else 2


if __name__ == "__main__":
    raise SystemExit(main())

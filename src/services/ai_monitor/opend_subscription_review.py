"""Deterministic *research-only* OpenD subscription review, never an executor.

Consumes existing AI Monitor watch ownership plus an independently verified
aggregate OpenD audit. A QUOTE slot is not proof of a K-line subscription slot:
no executable subscribe/unsubscribe instructions are emitted.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.services.ai_monitor.watch_universe import (
    WatchSource, WatchUniverseSnapshot,
)

_MAX_WATCHES = 512
_MAX_SUBSCRIBED = 2048
_MAX_AGE_SECONDS = 120
_MAX_REVIEW = 32
_SOURCE_PRIORITY = {
    WatchSource.PORTFOLIO: 0,
    WatchSource.USER_PINNED: 1,
    WatchSource.RADAR: 2,
}


def _symbol(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    symbol = value.strip().upper()
    if not symbol.startswith("US.") or not 1 <= len(symbol[3:]) <= 16:
        return None
    if any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in symbol[3:]):
        return None
    return symbol


def review_us_opend_subscription_capacity(
    snapshot: WatchUniverseSnapshot,
    *, subscribed_symbols: list[str] | tuple[str, ...],
    quota_verified: bool,
    total_used: int | None,
    remain: int | None,
    now_utc: datetime | None = None,
    max_review: int = 16,
) -> dict:
    """Rank *existing* watch needs; no market discovery, provider I/O or changes."""
    safety = {
        "schema": "stock_razor_us_opend_subscription_review_v0_1",
        "research_only": True,
        "provider_requests": 0,
        "provider_mutations": 0,
        "subscription_changes": "NONE",
        "subtype_entitlement": "NOT_VERIFIED",
        "execution_permission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False,
    }

    def blocked(reason: str) -> dict:
        return {**safety, "ok": False, "status": "BLOCKED",
                "reason": reason, "candidates_for_review": []}

    now = now_utc or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return blocked("INVALID_CLOCK")
    if not isinstance(snapshot, WatchUniverseSnapshot):
        return blocked("INVALID_WATCH_SNAPSHOT")
    generated = snapshot.generated_at
    age = (now.astimezone(timezone.utc) -
           generated.astimezone(timezone.utc)).total_seconds()
    if not -5 <= age <= _MAX_AGE_SECONDS:
        return blocked("STALE_OR_FUTURE_WATCH_SNAPSHOT")
    if (type(max_review) is not int or not 1 <= max_review <= _MAX_REVIEW
            or not isinstance(subscribed_symbols, (list, tuple))
            or len(subscribed_symbols) > _MAX_SUBSCRIBED):
        return blocked("INVALID_REVIEW_INPUT")
    if (quota_verified is not True or type(total_used) is not int
            or type(remain) is not int or not 0 <= total_used <= 10000
            or not 0 <= remain <= 10000 or total_used + remain > 10000):
        return blocked("AGGREGATE_QUOTA_UNVERIFIED")
    existing = set()
    for raw in subscribed_symbols:
        normalized = _symbol(raw)
        if normalized is None:
            return blocked("INVALID_SUBSCRIBED_SYMBOL")
        existing.add(normalized)
    if len(snapshot.watches) > _MAX_WATCHES:
        return blocked("WATCH_UNIVERSE_TOO_LARGE")
    candidates = {}
    for watch in snapshot.watches:
        if not watch.is_active or watch.identity.market != "us":
            continue
        symbol = _symbol(watch.identity.symbol)
        if symbol is None:
            return blocked("INVALID_WATCH_SYMBOL")
        if symbol in existing:
            continue
        sources = tuple(state.source for state in watch.sources)
        if not sources or any(source not in _SOURCE_PRIORITY for source in sources):
            return blocked("INVALID_WATCH_OWNERSHIP")
        priority = min(_SOURCE_PRIORITY[source] for source in sources)
        prior = candidates.get(symbol)
        if prior is None or priority < prior:
            candidates[symbol] = priority
    ordered = sorted(candidates.items(), key=lambda item: (item[1], item[0]))
    # Aggregate remaining capacity does not verify per-subtype entitlement,
    # OpenD connection ownership, simultaneous limits, or actual ability to
    # subscribe. It is *never* used to grant an executable plan.
    result = [{
        "symbol": symbol,
        "priority": ("PORTFOLIO", "USER_PINNED", "RADAR")[priority],
        "decision": "MANUAL_QUOTA_AND_ENTITLEMENT_REVIEW_REQUIRED",
    } for symbol, priority in ordered[:max_review]]
    return {
        **safety, "ok": True, "status": "REVIEW_ONLY",
        "watch_snapshot_age_seconds": round(age, 3),
        "aggregate_quota_verified": True,
        "aggregate_total_used": total_used,
        "aggregate_remaining": remain,
        "active_unsubscribed_count": len(ordered),
        "review_count": len(result),
        "truncated": len(ordered) > len(result),
        "candidates_for_review": result,
        "next_gate": "VERIFY_PER_SUBTYPE_ENTITLEMENT_AND_CONNECTION_QUOTA",
    }

"""Offline US watch churn stress simulation; NEVER an OpenD subscription plan.

Inputs are hypothetical ranked watch snapshots, not verified provider capacity.
Outputs are bounded aggregate counters only, without subscribe/unsubscribe
instructions, tickers, broker calls or admissions.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping

MAX_FRAMES = 240
MAX_SYMBOLS = 256


def _valid_us_symbol(raw: object) -> bool:
    return (
        isinstance(raw, str)
        and raw.startswith("US.")
        and 1 <= len(raw[3:]) <= 16
        and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in raw[3:])
    )


def simulate_us_watch_churn(
    ranked_frames: list[list[str]],
    *,
    hypothetical_slots: int = 8,
    min_consecutive_frames: int = 2,
    max_changes_per_window: int = 4,
    window_frames: int = 6,
) -> dict:
    """Simulate hysteresis, churn rate limiting, and capacity using no I/O.

    Every frame is a separate *hypothetical* ranked universe observation.
    A symbol must appear in >=min_consecutive_frames to enter, and be
    absent >=min_consecutive_frames to leave. Changes are limited to
    max_changes_per_window in any window_frames observations. No priority
    preemption of active watches is attempted.
    """
    safety = {
        "schema": "stock_razor_us_watch_churn_simulation_v0_1",
        "research_only": True,
        "hypothetical_inputs_only": True,
        "provider_requests": 0,
        "provider_mutations": 0,
        "subscription_changes": "NONE",
        "subtype_entitlement": "NOT_VERIFIED",
        "quota_qualification": "NOT_VERIFIED",
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }

    def blocked(reason: str) -> dict:
        return {**safety, "status": "BLOCKED", "reason": reason}

    if (not isinstance(ranked_frames, list)
            or not 1 <= len(ranked_frames) <= MAX_FRAMES
            or any(type(x) is not int for x in (
                hypothetical_slots, min_consecutive_frames,
                max_changes_per_window, window_frames))
            or not 1 <= hypothetical_slots <= MAX_SYMBOLS
            or not 1 <= min_consecutive_frames <= 20
            or not 1 <= max_changes_per_window <= MAX_SYMBOLS
            or not 1 <= window_frames <= MAX_FRAMES):
        return blocked("INVALID_SIMULATION_BOUNDS")

    for frame in ranked_frames:
        if (not isinstance(frame, list)
                or len(frame) > MAX_SYMBOLS
                or any(not _valid_us_symbol(symbol) for symbol in frame)
                or len(set(frame)) != len(frame)):
            return blocked("INVALID_HYPOTHETICAL_FRAME")

    active: set[str] = set()
    presence: dict[str, int] = {}
    absence: dict[str, int] = {}
    change_indices: deque[int] = deque()
    simulated_adds = 0
    simulated_removes = 0
    blocked_by_capacity = 0
    blocked_by_churn_budget = 0
    blocked_by_hysteresis = 0
    max_simultaneous = 0

    for index, frame in enumerate(ranked_frames):
        ranked = set(frame)
        for symbol in set(presence) | ranked:
            presence[symbol] = presence.get(symbol, 0) + 1 if symbol in ranked else 0
        for symbol in active:
            absence[symbol] = absence.get(symbol, 0) + 1 if symbol not in ranked else 0

        while change_indices and change_indices[0] <= index - window_frames:
            change_indices.popleft()

        # Simulated removals happen only after repeated absence. They do not
        # imply a real unsubscribe recommendation.
        for symbol in sorted(active):
            if symbol in ranked:
                continue
            if absence.get(symbol, 0) < min_consecutive_frames:
                blocked_by_hysteresis += 1
                continue
            if len(change_indices) >= max_changes_per_window:
                blocked_by_churn_budget += 1
                continue
            active.remove(symbol)
            absence.pop(symbol, None)
            change_indices.append(index)
            simulated_removes += 1

        # Rank order is preserved. Never preempt an active subscription based
        # on hypothetical candidate priority alone.
        for symbol in frame:
            if symbol in active:
                continue
            if presence[symbol] < min_consecutive_frames:
                blocked_by_hysteresis += 1
                continue
            if len(active) >= hypothetical_slots:
                blocked_by_capacity += 1
                continue
            if len(change_indices) >= max_changes_per_window:
                blocked_by_churn_budget += 1
                continue
            active.add(symbol)
            absence.pop(symbol, None)
            change_indices.append(index)
            simulated_adds += 1
        max_simultaneous = max(max_simultaneous, len(active))

    return {
        **safety,
        "status": "SIMULATION_ONLY",
        "frame_count": len(ranked_frames),
        "hypothetical_slots": hypothetical_slots,
        "simulated_add_count": simulated_adds,
        "simulated_remove_count": simulated_removes,
        "capacity_block_events": blocked_by_capacity,
        "churn_budget_block_events": blocked_by_churn_budget,
        "hysteresis_block_events": blocked_by_hysteresis,
        "final_hypothetical_watch_count": len(active),
        "max_hypothetical_watch_count": max_simultaneous,
        "next_gate": "VERIFY_REAL_PER_SUBTYPE_ENTITLEMENT_AND_CONNECTION_QUOTA",
    }

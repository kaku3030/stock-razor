#!/usr/bin/env python3
"""Finite public evidence projection of a private TickFlow WS protocol probe.

Read one private JSON summary from stdin, print only a strict allowlist.
Never emit symbols, prices, endpoint URL, API key, or arbitrary error strings.
This script cannot authorize live feed, Radar or broker trading.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_STATES = {"PASS", "FAIL", "NOT_VERIFIED"}
_WINDOW = {"COMPLETED", "TERMINATED_EARLY", "UNOBSERVED"}
_PROGRESS = {"OBSERVED_NOT_QUALIFIED", "INSUFFICIENT"}
_COUNTS = (
    "ack_messages", "invalid_ack_messages", "pre_ack_quote_frames",
    "quote_frames", "initial_snapshot_candidates", "post_initial_update_candidates",
    "duplicate_timestamp_count", "out_of_order_timestamp_count",
    "invalid_timestamp_count", "unknown_symbol_count",
    "protocol_error_frames", "invalid_frames",
)


def sanitize(raw: object, *, repo_sha: str) -> dict:
    if _HEX40.fullmatch(repo_sha) is None or not isinstance(raw, dict):
        raise ValueError("invalid provenance or protocol evidence")
    if raw.get("schema") != "stock_razor_tickflow_ws_ack_evidence_v0_1":
        raise ValueError("unexpected schema")
    if raw.get("protocol_acceptance_scope") != "ACK_ONLY_NOT_LIVE_QUALIFICATION":
        raise ValueError("protocol scope mismatch")
    for key in ("ws_handshake", "subscription_ack", "protocol_acceptance"):
        if raw.get(key) not in _STATES:
            raise ValueError("invalid protocol status")
    if raw.get("bounded_window_status") not in _WINDOW:
        raise ValueError("invalid window status")
    if raw.get("post_initial_progress_status") not in _PROGRESS:
        raise ValueError("invalid progress status")
    if raw.get("post_initial_update_not_proven_live") is not True:
        raise ValueError("unqualified update claim")
    if raw.get("continuous_feed_qualified") is not False:
        raise ValueError("source qualification forbidden")
    if raw.get("source_arbiter_admission") != "BLOCKED" or raw.get("radar_admission") != "BLOCKED":
        raise ValueError("admission forbidden")
    if any(raw.get(key) is not False for key in ("live_trade", "canonical_write", "order_execution")):
        raise ValueError("trading or writes forbidden")

    counts = {}
    for key in _COUNTS:
        value = raw.get(key)
        if type(value) is not int or not 0 <= value <= 1_000_000:
            raise ValueError("invalid bounded counter")
        counts[key] = value

    # ACK, full-window duration and provider timestamp advances are independent
    # evidence. Not even their conjunction establishes provider currentness,
    # delivery SLO, independent historical parity or verified live admission.
    complete = (
        raw["protocol_acceptance"] == "PASS"
        and raw["ws_handshake"] == "PASS"
        and raw["subscription_ack"] == "PASS"
        and raw["bounded_window_status"] == "COMPLETED"
        and raw["post_initial_progress_status"] == "OBSERVED_NOT_QUALIFIED"
        and counts["post_initial_update_candidates"] >= 2
        and counts["protocol_error_frames"] == 0
        and counts["invalid_ack_messages"] == 0
    )
    return {
        "schema": "stock_razor_tickflow_ws_ack_sanitized_v0_1",
        "source_revision": repo_sha,
        "request_scope": "DIRECT_QUOTE_WS_PROTOCOL_ONLY",
        "protocol_acceptance": raw["protocol_acceptance"],
        "ws_handshake": raw["ws_handshake"],
        "subscription_ack": raw["subscription_ack"],
        "bounded_window_status": raw["bounded_window_status"],
        "post_initial_progress_status": raw["post_initial_progress_status"],
        "protocol_progress_observation": (
            "OBSERVED_NOT_QUALIFIED" if complete else "NOT_VERIFIED"
        ),
        "counters": counts,
        "data_qualification": "NOT_VERIFIED",
        "continuous_feed_qualified": False,
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "paper_auto_ready": "NO",
        "live_trade": False,
        "trade_execution": "NO",
        "canonical_write": False,
        "order_execution": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-sha", required=True)
    args = parser.parse_args()
    try:
        raw = json.load(sys.stdin)
        result = sanitize(raw, repo_sha=args.repo_sha)
    except (ValueError, TypeError, KeyError, OverflowError):
        # Do not echo arbitrary invalid user/provider evidence, secret or URL.
        print(json.dumps({
            "schema": "stock_razor_tickflow_ws_ack_sanitized_v0_1",
            "protocol_progress_observation": "NOT_VERIFIED",
            "data_qualification": "NOT_VERIFIED",
            "radar_admission": "BLOCKED",
            "source_arbiter_admission": "BLOCKED",
            "live_trade": False,
            "trade_execution": "NO",
            "failure_class": "INVALID_EVIDENCE",
        }, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

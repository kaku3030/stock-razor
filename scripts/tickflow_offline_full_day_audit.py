"""Compose existing TickFlow/reference OHLCV parity and full-day session grid.

Offline only: no TickFlow SDK/network, canonical writes, accounts, billing,
subscription changes, or admission. REAL_CAPTURED is self-declared metadata,
not independently established source provenance.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json

from data_provider.tickflow_cn_session_coverage import (
    review_a_share_minute_session,
)
from data_provider.tickflow_history_contract import HistoryRow
from scripts.tickflow_offline_bar_crosscheck import (
    FixtureError,
    _read_fixture,
    compare_files,
)


def audit_offline_full_day(
    tickflow_path: str,
    reference_path: str,
    *,
    trading_day: date,
    trading_session_confirmed: bool = False,
    timestamp_semantic_verified: bool = False,
) -> dict:
    """Independent label grid + existing OHLCV comparison, never source PASS."""
    safe = {
        "schema": "stock_razor_cn_full_day_offline_audit_v0_1",
        "provider_requests": 0,
        "provider_quota_reserved": 0,
        "canonical_write": False,
        "research_only": True,
        "provenance_verified": False,
        "data_qualification": "NOT_VERIFIED",
        "bar_closure_qualification": "NOT_VERIFIED",
        "trading_calendar_qualification": "NOT_VERIFIED",
        "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED",
        "paper_auto_ready": False,
        "live_trade": False,
    }

    def stop(status: str, reason: str, **counts) -> dict:
        return {**safe, "status": status, "reason": reason, **counts}

    if type(trading_day) is not date or trading_day.weekday() >= 5:
        return stop("UNKNOWN", "TRADING_DAY_CALENDAR_UNVERIFIED")
    if trading_session_confirmed is not True:
        return stop("UNKNOWN", "TRADING_SESSION_CONFIRMATION_MISSING")
    if timestamp_semantic_verified is not True:
        return stop("UNKNOWN", "TIMESTAMP_SEMANTIC_NOT_VERIFIED")

    try:
        # Reuses the existing strict, minimal, offline OHLCV fixture parser.
        tick = _read_fixture(tickflow_path)
        ref = _read_fixture(reference_path)
    except FixtureError as exc:
        return stop("BLOCKED", str(exc))
    # A complete regular 15m/60m session requires 16/4 bars per ETF.
    required = {"15m": 16, "60m": 4}
    if tick["timeframe"] not in required or ref["timeframe"] != tick["timeframe"]:
        return stop("BLOCKED", "TIMEFRAME_MISMATCH")
    if tick["symbol"] != ref["symbol"]:
        return stop("BLOCKED", "SYMBOL_MISMATCH")

    cross = compare_files(
        tickflow_path, reference_path,
        min_overlap=required[tick["timeframe"]],
    )
    # compare_files retains independent source, OHLCV/unit and alignment checks.
    if not cross.get("comparison_agreement", False):
        return stop(
            "BLOCKED", "BAR_PARITY_OR_OVERLAP_MISMATCH",
            aligned_bars=cross.get("aligned_bars", 0),
            missing_in_tickflow=cross.get("missing_in_tickflow", 0),
            missing_in_reference=cross.get("missing_in_reference", 0),
        )

    rows = tuple(
        HistoryRow(
            tick["symbol"],
            datetime.fromisoformat(stamp),
            "TICKFLOW",
        )
        for stamp in tick["rows"]
    )
    coverage = review_a_share_minute_session(
        rows,
        expected_symbols=(tick["symbol"],),
        trading_day=trading_day,
        timeframe=tick["timeframe"],
        timestamp_semantic="BAR_END",
        trading_session_confirmed=True,
        timestamp_semantic_verified=True,
    )
    counts = {
        "timeframe": tick["timeframe"],
        "grid_status": coverage.status,
        "expected_bars": coverage.expected_bars,
        "observed_bars": coverage.observed_bars,
        "missing_bars": coverage.missing_bars,
        "unexpected_bars": coverage.unexpected_bars,
        "duplicate_bars": coverage.duplicate_bars,
        "aligned_bars": cross["aligned_bars"],
        "ohlcv_mismatch_fields": dict(cross["mismatch_counts"]),
    }
    if coverage.status != "REVIEW_ONLY":
        return stop("BLOCKED", "FULL_DAY_SESSION_GRID_MISMATCH", **counts)
    if tick["origin"] != "REAL_CAPTURED" or ref["origin"] != "REAL_CAPTURED":
        return stop("SYNTHETIC_TEST_ONLY", "SELF_DECLARED_SYNTHETIC_CAPTURE", **counts)
    return stop(
        "REVIEW_ONLY", "SELF_DECLARED_CAPTURE_AGREEMENT_NOT_PROVENANCE",
        **counts,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline full-day TickFlow ETF parity review")
    parser.add_argument("--tickflow-fixture", required=True)
    parser.add_argument("--reference-fixture", required=True)
    parser.add_argument("--trading-day", required=True)
    parser.add_argument("--trading-session-confirmed", action="store_true")
    parser.add_argument("--timestamp-semantic-verified", action="store_true")
    args = parser.parse_args()
    try:
        day = date.fromisoformat(args.trading_day)
    except ValueError:
        day = None
    result = audit_offline_full_day(
        args.tickflow_fixture, args.reference_fixture,
        trading_day=day,
        trading_session_confirmed=args.trading_session_confirmed,
        timestamp_semantic_verified=args.timestamp_semantic_verified,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in ("REVIEW_ONLY", "SYNTHETIC_TEST_ONLY") else 2


if __name__ == "__main__":
    raise SystemExit(main())

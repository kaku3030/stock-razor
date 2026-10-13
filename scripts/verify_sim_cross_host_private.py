#!/usr/bin/env python3
"""Private, LOCAL-ONLY Windows-vs-AWS US SIM readback comparison.

Consumes two explicitly prepared private JSON files; never fetches broker
data, stores output, hashes account IDs, prints raw rows or places orders.
No source of independent fills is inferred from position equality.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from src.services.legacy_sim_inventory import LegacySimPosition
from src.services.sim_account_continuity import (
    SimAccountHostObservation,
    compare_local_cloud_sim,
)

SCHEMA = "stock_razor_private_us_sim_readback_v0_1"
MAX_INPUT_BYTES = 32768
MAX_POSITION_ROWS = 200
FIELDS = frozenset({
    "schema", "account_id", "source", "account_generation",
    "observed_at_utc", "account_mode", "market", "authenticated", "positions",
})
POSITION_FIELDS = frozenset({"symbol", "side", "quantity"})
APPROVAL_SCHEMA = "stock_razor_approved_us_sim_account_v0_1"
APPROVAL_FIELDS = frozenset({"schema", "account_id"})


class InvalidReadback(ValueError):
    """Never contains a private value in its message."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidReadback("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _read_snapshot(path: str) -> SimAccountHostObservation:
    """Reject unknown shapes, oversized input, and unparseable private rows."""
    try:
        input_path = Path(path)
        if input_path.is_symlink() or not input_path.is_file():
            raise InvalidReadback("PRIVATE_INPUT_UNAVAILABLE")
        if input_path.stat().st_size > MAX_INPUT_BYTES:
            raise InvalidReadback("PRIVATE_INPUT_TOO_LARGE")
        with input_path.open("rb") as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise InvalidReadback("PRIVATE_INPUT_TOO_LARGE")
        obj = json.loads(raw, object_pairs_hook=_unique_object)
    except InvalidReadback:
        raise
    except RecursionError:
        # A syntactically valid but excessively nested JSON document is not
        # an admissible private readback schema. Do not echo parser details.
        raise InvalidReadback("PRIVATE_SCHEMA_INVALID") from None
    except (OSError, UnicodeError, ValueError, TypeError):
        raise InvalidReadback("PRIVATE_INPUT_INVALID") from None
    if not isinstance(obj, dict) or obj.keys() != FIELDS:
        raise InvalidReadback("PRIVATE_SCHEMA_INVALID")
    if obj["schema"] != SCHEMA:
        raise InvalidReadback("PRIVATE_SCHEMA_VERSION_INVALID")
    at = obj["observed_at_utc"]
    if not isinstance(at, str) or len(at) > 40:
        raise InvalidReadback("OBSERVATION_TIME_INVALID")
    try:
        observed = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        raise InvalidReadback("OBSERVATION_TIME_INVALID") from None
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise InvalidReadback("OBSERVATION_TIME_INVALID")

    positions = obj["positions"]
    if not isinstance(positions, list) or len(positions) > MAX_POSITION_ROWS:
        raise InvalidReadback("POSITION_ROWS_INVALID")
    parsed = []
    for row in positions:
        if not isinstance(row, dict) or row.keys() != POSITION_FIELDS:
            raise InvalidReadback("POSITION_ROWS_INVALID")
        value = row["quantity"]
        if not isinstance(value, str) or len(value) > 40:
            raise InvalidReadback("POSITION_QUANTITY_INVALID")
        try:
            amount = Decimal(value)
        except (InvalidOperation, ValueError):
            raise InvalidReadback("POSITION_QUANTITY_INVALID") from None
        parsed.append(LegacySimPosition(row["symbol"], row["side"], amount))
    return SimAccountHostObservation(
        account_id=obj["account_id"],
        source=obj["source"],
        account_generation=obj["account_generation"],
        observed_at_utc=observed,
        account_mode=obj["account_mode"],
        market=obj["market"],
        authenticated=obj["authenticated"],
        positions=tuple(parsed),
    )



def _read_approved_account(path: str | None) -> str:
    """Out-of-band operator approval in a *third private file*, never argv.

    Caller must independently establish approval provenance and protect the
    file. Possession of this JSON is not independent broker consent proof.
    """
    if not isinstance(path, str) or not path:
        raise InvalidReadback("APPROVED_SIM_ACCOUNT_FILE_REQUIRED")
    try:
        file = Path(path)
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 1024:
            raise InvalidReadback("APPROVED_SIM_ACCOUNT_FILE_INVALID")
        with file.open("rb") as handle:
            raw = handle.read(1025)
        if len(raw) > 1024:
            raise InvalidReadback("APPROVED_SIM_ACCOUNT_FILE_INVALID")
        approval = json.loads(raw, object_pairs_hook=_unique_object)
    except InvalidReadback:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        raise InvalidReadback("APPROVED_SIM_ACCOUNT_FILE_INVALID") from None
    if not isinstance(approval, dict) or approval.keys() != APPROVAL_FIELDS:
        raise InvalidReadback("APPROVED_SIM_ACCOUNT_SCHEMA_INVALID")
    if approval["schema"] != APPROVAL_SCHEMA:
        raise InvalidReadback("APPROVED_SIM_ACCOUNT_SCHEMA_INVALID")
    value = approval["account_id"]
    if not (
        isinstance(value, str) and value.isascii() and value.isdigit()
        and 1 <= len(value) <= 20
    ):
        raise InvalidReadback("APPROVED_SIM_ACCOUNT_ID_INVALID")
    return value



def verify_private_readbacks(
    windows_path: str,
    aws_path: str,
    *,
    approved_account_file: str | None = None,
    now_utc: datetime | None = None,
) -> dict:
    """Sanitized report; never includes IDs, symbols, quantities or prices."""
    safe = {
        "schema": "stock_razor_private_us_sim_comparison_v0_1",
        "paper_auto_ready": False,
        "broker_mutation_allowed": False,
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "live_trade": False,
        "independent_realized_fills_proven": False,
        "provider_calls": 0,
        "orders_sent": 0,
        "private_file_writes": 0,
    }
    try:
        approved_id = _read_approved_account(approved_account_file)
        local = _read_snapshot(windows_path)
        cloud = _read_snapshot(aws_path)
        result = compare_local_cloud_sim(
            local, cloud,
            expected_account_id=approved_id,
            now_utc=now_utc or datetime.now(timezone.utc),
        )
    except InvalidReadback as exc:
        return {
            **safe, "status": "BLOCKED", "reason": str(exc),
            "position_count": 0, "same_account_id": False,
            "same_positions": False,
        }
    except (TypeError, ValueError, OverflowError):
        return {
            **safe, "status": "BLOCKED", "reason": "PRIVATE_DATA_REVIEW_FAILED",
            "position_count": 0, "same_account_id": False,
            "same_positions": False,
        }
    return {
        **safe, "status": result.status, "reason": result.reason,
        "position_count": result.position_count,
        "same_account_id": result.same_account_id,
        "same_positions": result.same_positions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Private read-only US SIM cross-host review; no broker I/O"
    )
    parser.add_argument("--windows-file", required=True)
    parser.add_argument("--aws-file", required=True)
    # Never provide an account ID directly in argv or env: both can leak.
    parser.add_argument("--approved-account-file", required=True)
    args = parser.parse_args()
    result = verify_private_readbacks(
        args.windows_file, args.aws_file,
        approved_account_file=args.approved_account_file,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "MATCHED_FOR_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())

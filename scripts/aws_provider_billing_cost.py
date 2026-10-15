"""Read-only AWS Cost Explorer cost summary for unified provider watch.

AWS has no generic API prepaid wallet balance; Cost Explorer's estimated
unblended spend MUST NOT be reported as exact cash remaining, credits, or bill.
Never emit AWS CLI error text, account identifiers, environment, or credentials.
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

MAX_OUTPUT_BYTES = 128_000
AWS_REGION = "us-east-1"  # Cost Explorer billing endpoint, independent of EC2 region.


def parse_monthly_cost(body: bytes) -> tuple[str, bool]:
    if not body or len(body) > MAX_OUTPUT_BYTES:
        raise ValueError("invalid_response_length")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_schema")
    series = payload.get("ResultsByTime")
    if not isinstance(series, list) or len(series) != 1:
        raise ValueError("incomplete_monthly_results")
    record = series[0]
    if not isinstance(record, dict) or not isinstance(record.get("Total"), dict):
        raise ValueError("invalid_cost_record")
    data = record["Total"].get("UnblendedCost")
    if not isinstance(data, dict) or data.get("Unit") != "USD":
        raise ValueError("invalid_currency")
    amount = data.get("Amount")
    if not isinstance(amount, str) or not 1 <= len(amount) <= 48:
        raise ValueError("invalid_amount")
    try:
        value = Decimal(amount)
    except InvalidOperation as exc:
        raise ValueError("invalid_amount") from exc
    if not value.is_finite() or value < 0 or value >= Decimal("1000000000"):
        raise ValueError("invalid_amount")
    estimated = record.get("Estimated")
    if type(estimated) is not bool:
        raise ValueError("unknown_estimation_status")
    return str(value.quantize(Decimal("0.01"))), estimated


def aws_cost_mtd(now: datetime, *, runner=subprocess.run) -> tuple[str, str | None, bool | None]:
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    utc_today = now.astimezone(timezone.utc).date()
    start = utc_today.replace(day=1)
    end = utc_today + timedelta(days=1)  # AWS time period End is exclusive.
    command = [
        "aws", "ce", "get-cost-and-usage",
        "--time-period", f"Start={start.isoformat()},End={end.isoformat()}",
        "--granularity", "MONTHLY",
        "--metrics", "UnblendedCost",
        "--region", AWS_REGION, "--output", "json",
    ]
    try:
        p = runner(command, capture_output=True, check=False, timeout=18)
    except (OSError, subprocess.TimeoutExpired):
        return "UNKNOWN", None, None
    if p.returncode:
        # Never log stderr, which may include request/account identifiers.
        return "NOT_AUTHORIZED_OR_UNAVAILABLE", None, None
    try:
        amount, estimated = parse_monthly_cost(p.stdout)
        return "OK", amount, estimated
    except (ValueError, TypeError):
        return "UNKNOWN", None, None


def main() -> int:
    from pathlib import Path
    import os
    status, amount, estimated = aws_cost_mtd(datetime.now(timezone.utc))
    # Only this narrow output crosses the role-authenticated job boundary.
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"status={status}\n")
            handle.write(f"mtd_usd={amount or ''}\n")
            handle.write(f"estimated={'true' if estimated is True else 'false' if estimated is False else 'unknown'}\n")
    print("AWS_COST_WATCH=" + status)
    return 0  # UNKNOWN is reported as unknown, never guessed or silently ignored.


if __name__ == "__main__":
    raise SystemExit(main())

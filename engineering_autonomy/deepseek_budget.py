"""DeepSeek account budget gate and Aider token telemetry for test-only autonomy.

Only the official DeepSeek balance GET reads the billing account. No chat/API
completion is sent by this module. Never print secrets, account payloads,
prompts, response text, Aider raw analytics or precise account balances.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, InvalidOperation
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

BALANCE_ENDPOINT = "https://api.deepseek.com/user/balance"
LIMIT_BYTES = 16_384
MAX_USAGE_BYTES = 2_000_000
# These are alert thresholds, not provider pricing and not currency conversions.
LOW_BALANCE = {"CNY": Decimal("10"), "USD": Decimal("2")}
STATUSES = frozenset({"OK", "LOW", "EMPTY", "UNAVAILABLE", "UNKNOWN"})
ISSUE_TITLE = "STOCK RAZOR: DeepSeek API recharge required"


def _decimal(value: object) -> Decimal:
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9]\d{0,9})(?:\.\d{1,8})?", value):
        raise ValueError("malformed amount")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("malformed amount") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("invalid amount")
    return number


def classify_balance(body: bytes) -> tuple[str, list[str]]:
    """Strictly validate provider data; don't confuse unknown with empty."""
    if not body or len(body) > LIMIT_BYTES:
        raise ValueError("bad body size")
    payload = json.loads(body)
    if not isinstance(payload, dict) or type(payload.get("is_available")) is not bool:
        raise ValueError("bad availability")
    balances = payload.get("balance_infos")
    if not isinstance(balances, list) or not 1 <= len(balances) <= 2:
        raise ValueError("bad balance list")
    values: dict[str, Decimal] = {}
    for info in balances:
        if not isinstance(info, dict):
            raise ValueError("bad balance")
        currency = info.get("currency")
        if not isinstance(currency, str) or currency not in LOW_BALANCE or currency in values:
            raise ValueError("unknown or duplicate currency")
        total = _decimal(info.get("total_balance"))
        granted = _decimal(info.get("granted_balance"))
        topped_up = _decimal(info.get("topped_up_balance"))
        # Provider amounts may be rounded; avoid strict equality on subtotals.
        if granted > total + Decimal("0.01") or topped_up > total + Decimal("0.01"):
            raise ValueError("inconsistent balance")
        values[currency] = total
    currencies = sorted(values)
    if not payload["is_available"]:
        return ("EMPTY" if all(x == 0 for x in values.values()) else "UNAVAILABLE"), currencies
    if all(x == 0 for x in values.values()):
        return "EMPTY", currencies
    if all(amount <= LOW_BALANCE[currency] for currency, amount in values.items()):
        return "LOW", currencies
    return "OK", currencies


def fetch_balance(key: str, opener=urllib.request.urlopen) -> tuple[str, list[str]]:
    if not key:
        raise ValueError("missing key")
    request = urllib.request.Request(
        BALANCE_ENDPOINT,
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        method="GET",
    )
    with opener(request, timeout=12) as response:
        if response.status != 200:
            raise ValueError("non-200 balance response")
        return classify_balance(response.read(LIMIT_BYTES + 1))


def _write_status(path: Path, status: str, currencies: list[str]) -> None:
    # Only categorical data. Account balances, key, response bodies are never persisted.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": 1, "status": status, "currencies": currencies}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def check_balance(path: Path, *, monitor: bool = False) -> int:
    try:
        status, currencies = fetch_balance(os.environ.get("DEEPSEEK_API_KEY", ""))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, urllib.error.URLError,
            TimeoutError, OSError, UnicodeDecodeError):
        status, currencies = "UNKNOWN", []
    _write_status(path, status, currencies)
    print(f"DEEPSEEK_BUDGET={status};CURRENCIES={','.join(currencies) if currencies else 'NA'}", flush=True)
    # Fail closed for low funds, unavailable balances or read errors. Never call a model.
    return 0 if status == "OK" or (monitor and status in {"LOW", "EMPTY", "UNAVAILABLE"}) else 2


def read_status(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(payload, dict) or set(payload) != {"schema", "status", "currencies"}
            or payload["schema"] != 1 or payload["status"] not in STATUSES
            or not isinstance(payload["currencies"], list)
            or any(x not in LOW_BALANCE for x in payload["currencies"])):
        raise ValueError("invalid status report")
    return payload["status"]


def summarize_usage(path: Path) -> dict[str, object]:
    """Whitelist only Aider 'message_send' counters; NEVER publish raw events."""
    if not path.is_file():
        return {"status": "NO_DATA", "requests": 0}
    if path.stat().st_size > MAX_USAGE_BYTES:
        return {"status": "UNVERIFIED", "requests": 0}
    sent = received = requests = 0
    estimated_cost = Decimal(0)
    cost_complete = True
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            event = json.loads(line)
            if not isinstance(event, dict) or event.get("event") != "message_send":
                continue
            props = event.get("properties")
            if not isinstance(props, dict):
                raise ValueError("invalid properties")
            a, b = props.get("prompt_tokens"), props.get("completion_tokens")
            if type(a) is not int or type(b) is not int or not 0 <= a <= 10**9 or not 0 <= b <= 10**9:
                raise ValueError("invalid usage counters")
            n = props.get("total_tokens")
            if n is not None and (type(n) is not int or n != a + b):
                raise ValueError("inconsistent token count")
            price = props.get("cost")
            if type(price) not in (int, float) or not math.isfinite(price) or price < 0:
                cost_complete = False
            else:
                estimated_cost += Decimal(str(price))
            sent += a
            received += b
            requests += 1
        if not requests:
            return {"status": "NO_DATA", "requests": 0}
        result: dict[str, object] = {
            "status": "OBSERVED", "requests": requests,
            "input_tokens": sent, "output_tokens": received,
            "total_tokens": sent + received,
        }
        # Aider pricing is approximate; NOT the actual DeepSeek balance deduction.
        result["estimated_cost_usd"] = str(round(estimated_cost, 6)) if cost_complete else None
        return result
    except (ValueError, TypeError, OverflowError, json.JSONDecodeError, UnicodeDecodeError):
        return {"status": "UNVERIFIED", "requests": 0}


def usage_command(path: Path, output: Path) -> int:
    result = summarize_usage(path)
    result["schema"] = 1
    run_id = os.getenv("GITHUB_RUN_ID", "")
    result["run_id"] = run_id if re.fullmatch(r"\d{1,20}", run_id) else "local"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "DEEPSEEK_USAGE=" + str(result["status"]) + ";REQUESTS=" + str(result["requests"])
        + ";INPUT_TOKENS=" + str(result.get("input_tokens", "NA"))
        + ";OUTPUT_TOKENS=" + str(result.get("output_tokens", "NA")),
        flush=True,
    )
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(
                "\n### DeepSeek / Aider token usage\n"
                + f"- Evidence: {result['status']} (not a billing invoice)\n"
                + f"- Requests: {result['requests']}\n"
                + f"- Input tokens: {result.get('input_tokens', 'UNKNOWN')}\n"
                + f"- Output tokens: {result.get('output_tokens', 'UNKNOWN')}\n"
                + f"- Aider estimated cost (USD): {result.get('estimated_cost_usd', 'UNKNOWN')}\n"
            )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    balance = sub.add_parser("check")
    balance.add_argument("--status-file", type=Path, required=True)
    balance.add_argument("--monitor", action="store_true", help="allow a verified low/empty status for alerting")
    usage = sub.add_parser("usage")
    usage.add_argument("--analytics-log", type=Path, required=True)
    usage.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "check":
        return check_balance(args.status_file, monitor=args.monitor)
    return usage_command(args.analytics_log, args.output)


if __name__ == "__main__":
    sys.exit(main())

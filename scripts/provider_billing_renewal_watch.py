#!/usr/bin/env python3
"""Cloud-only read-only provider billing and renewal watch.

The public OpenAI organization Costs/Usage APIs require an ADMIN key.
Those APIs do not attest to prepaid credit balance; a user-supplied
credit snapshot can produce ONLY an explicitly labelled estimate.
No credentials, raw responses, prices, or personal account details in logs.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import urllib.error
import urllib.parse
import urllib.request

OPENAI_API = "https://api.openai.com/v1"
COSTS = "/organization/costs"
USAGE = "/organization/usage/completions"
ALLOWED_CURRENCIES = {"usd"}
DUE_BANDS = (30, 14, 7, 3, 1, 0)


def positive_money(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid_money")
    try:
        money = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError("invalid_money") from None
    if not money.is_finite() or money < 0:
        raise ValueError("invalid_money")
    return money


def optional_money(value: str | None) -> Decimal | None:
    return positive_money(value) if value not in (None, "") else None


def utc_date(value: str | None) -> date | None:
    if value in (None, ""):
        return None
    if len(value) != 10 or date.fromisoformat(value).isoformat() != value:
        raise ValueError("invalid_date")
    return date.fromisoformat(value)


def _get_json(path: str, admin_key: str, start: int, end: int) -> dict:
    if not admin_key or path not in (COSTS, USAGE):
        raise ValueError("invalid_endpoint_or_key")
    qs = urllib.parse.urlencode({"start_time": start, "end_time": end, "limit": 35, "bucket_width": "1d"})
    req = urllib.request.Request(
        OPENAI_API + path + "?" + qs,
        headers={"Authorization": "Bearer " + admin_key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = response.read(500_001)
    except urllib.error.HTTPError as exc:
        # Never retain vendor-supplied error body (may contain private data).
        raise ValueError("http_" + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError):
        raise ValueError("network_error") from None
    if len(payload) > 500_000:
        raise ValueError("oversized_response")
    try:
        obj = json.loads(payload)
    except (TypeError, UnicodeError, ValueError):
        raise ValueError("invalid_json") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), list):
        raise ValueError("invalid_schema")
    if obj.get("has_more") is not False:
        # Never silently omit extra cost buckets when paging is unverified.
        raise ValueError("incomplete_page")
    return obj


def cost_usd(page: dict) -> Decimal:
    total = Decimal("0")
    for bucket in page["data"]:
        if not isinstance(bucket, dict) or not isinstance(bucket.get("results"), list):
            raise ValueError("invalid_cost_bucket")
        for item in bucket["results"]:
            if not isinstance(item, dict) or not isinstance(item.get("amount"), dict):
                raise ValueError("invalid_cost_amount")
            if item["amount"].get("currency") not in ALLOWED_CURRENCIES:
                raise ValueError("unexpected_currency")
            total += positive_money(item["amount"].get("value"))
    return total


def completion_tokens(page: dict) -> dict:
    totals = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
    names = {"requests": "num_model_requests", "input_tokens": "input_tokens",
             "output_tokens": "output_tokens"}
    for bucket in page["data"]:
        if not isinstance(bucket, dict) or not isinstance(bucket.get("results"), list):
            raise ValueError("invalid_usage_bucket")
        for row in bucket["results"]:
            if not isinstance(row, dict):
                raise ValueError("invalid_usage_row")
            for name, field in names.items():
                value = row.get(field)
                if type(value) is not int or value < 0:
                    raise ValueError("invalid_usage_value")
                totals[name] += value
    return totals


def renewal_alert(renewal: date | None, today: date) -> str | None:
    if renewal is None:
        return None
    days = (renewal - today).days
    if days in DUE_BANDS:
        return "TickFlow Expert renews in " + str(days) + "d on " + renewal.isoformat()
    if days < 0 and (abs(days) == 1 or abs(days) % 7 == 0):
        return "TickFlow renewal date passed " + str(abs(days)) + "d ago; payment status UNKNOWN"
    return None


def _utc_midnight(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _usd(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01")))


def evaluate(now: datetime, *, env: dict[str, str], fetch=_get_json) -> tuple[list[str], list[str]]:
    """Return (safe summary lines, alert lines). No trading/secret side effects."""
    if now.tzinfo is None:
        raise ValueError("timezone_required")
    today = now.astimezone(timezone.utc).date()
    month = today.replace(day=1)
    end = int(now.timestamp())
    report = ["STOCK RAZOR provider lifecycle — UTC " + today.isoformat()]
    alerts = []
    admin = env.get("OPENAI_ADMIN_KEY", "")
    budget = optional_money(env.get("OPENAI_MONTHLY_BUDGET_USD"))
    baseline = optional_money(env.get("OPENAI_CREDIT_SNAPSHOT_USD"))
    baseline_date = utc_date(env.get("OPENAI_CREDIT_SNAPSHOT_DATE_UTC"))
    renewal = utc_date(env.get("TICKFLOW_RENEWAL_DATE"))
    if (baseline is None) != (baseline_date is None):
        raise ValueError("incomplete_openai_credit_snapshot")
    if admin:
        try:
            month_cost = cost_usd(fetch(COSTS, admin, _utc_midnight(month), end))
            tokens = completion_tokens(fetch(USAGE, admin, _utc_midnight(month), end))
            report.append("OpenAI API MTD spend $" + _usd(month_cost) + " / requests "
                          + str(tokens["requests"]) + " / input tokens "
                          + str(tokens["input_tokens"]) + " / output tokens "
                          + str(tokens["output_tokens"]))
            if budget is not None:
                left = budget - month_cost
                report.append("Monthly user-defined budget $" + _usd(budget)
                              + "; remaining allowance $" + _usd(max(left, Decimal("0"))))
                if budget > 0 and month_cost >= budget * Decimal("0.8"):
                    alerts.append("OpenAI monthly user-defined budget >= 80% used; review limits")
                if budget == 0:
                    alerts.append("OpenAI monthly user-defined budget is zero")
            if baseline is not None and baseline_date is not None:
                if baseline_date > today or (today - baseline_date).days > 31:
                    raise ValueError("credit_snapshot_out_of_range")
                since = cost_usd(fetch(COSTS, admin, _utc_midnight(baseline_date), end))
                estimate = baseline - since
                report.append("OpenAI PREPAID ESTIMATE (not balance API) $"
                              + _usd(max(Decimal("0"), estimate)))
                if estimate <= Decimal("2"):
                    alerts.append("OpenAI estimated prepaid credit <= $2 (not authoritative); confirm dashboard")
        except ValueError as exc:
            # Exception code is fixed by this module, not vendor response text.
            report.append("OpenAI usage/cost=UNKNOWN (" + str(exc) + ")")
            alerts.append("OpenAI usage/cost monitoring unavailable — inspect Admin API access")
    else:
        report.append("OpenAI usage/cost=UNKNOWN (OPENAI_ADMIN_KEY not configured)")
        if today.weekday() == 0:
            alerts.append("Configure OPENAI_ADMIN_KEY secret for read-only OpenAI org usage")
    report.append("OpenAI exact prepaid balance=UNKNOWN (not provided by Costs API)")
    if renewal is None:
        report.append("TickFlow monthly next renewal=UNKNOWN (date not configured)")
        if today.weekday() == 0:
            alerts.append("Set TICKFLOW_RENEWAL_DATE (YYYY-MM-DD) to enable expiry warnings")
    else:
        report.append("TickFlow Expert next renewal date=" + renewal.isoformat())
        reminder = renewal_alert(renewal, today)
        if reminder:
            alerts.append(reminder)
    report.append("OpenD cost/expiry watch=EXCLUDED (user says free)")
    return report, alerts


def discord_send(webhook: str, content: str) -> None:
    if not webhook.startswith("https://discord.com/api/webhooks/") and not webhook.startswith("https://discordapp.com/api/webhooks/"):
        raise ValueError("invalid_discord_endpoint")
    data = json.dumps({"content": content[:1900], "allowed_mentions": {"parse": []}}).encode()
    request = urllib.request.Request(webhook, data=data,
                    headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            if response.status not in (200, 204):
                raise ValueError("discord_non_success")
    except (urllib.error.URLError, TimeoutError, urllib.error.HTTPError):
        raise ValueError("discord_delivery_failed") from None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--send-report", action="store_true", help="Send a sanitized one-off manual channel test")
    args = p.parse_args()
    env = dict(os.environ)
    now = datetime.now(timezone.utc)
    try:
        if args.dry_run:
            report, alerts = evaluate(now, env={
                "TICKFLOW_RENEWAL_DATE": (now.date()).isoformat(),
                "OPENAI_MONTHLY_BUDGET_USD": "10",
            })
            assert any("TickFlow" in a for a in alerts)
            print("PROVIDER_BILLING_WATCH=DRY_RUN_PASS (no HTTP calls or message)")
            return 0
        report, alerts = evaluate(now, env=env)
        # Weekly informational summary; alerts are sent on any day.
        dispatch = bool(alerts) or now.weekday() == 0 or args.send_report
        if not dispatch:
            print("PROVIDER_BILLING_WATCH=CHECK_OK_NO_ALERT")
            return 0
        candidates = tuple(dict.fromkeys(x for x in
            (env.get("DISCORD_RADAR_WEBHOOK_URL"),env.get("DISCORD_WEBHOOK_URL")) if x))
        if not candidates:
            print("PROVIDER_BILLING_WATCH=NOTIFICATION_BLOCKED_NO_WEBHOOK")
            return 2
        content = "\n".join(report + (["⚠️ " + msg for msg in alerts] if alerts else []))
        for index, webhook in enumerate(candidates):
            try:
                discord_send(webhook, content)
            except ValueError as exc:
                # Only local fixed-code messages. Never log actual webhook,
                # response body, token, or provider supplied error text.
                reason = exc.args[0] if exc.args else "unclassified"
                if reason not in ("invalid_discord_endpoint", "discord_non_success",
                                  "discord_delivery_failed"):
                    reason = "unclassified"
                print("PROVIDER_BILLING_WATCH=WEBHOOK_REJECTED_" + str(index+1)
                      + "_" + reason.upper())
                continue
            print("PROVIDER_BILLING_WATCH=ALERT_DISPATCHED" if alerts else
                  "PROVIDER_BILLING_WATCH=WEEKLY_REPORT_DISPATCHED")
            return 0
        print("PROVIDER_BILLING_WATCH=ALL_WEBHOOKS_FAILED")
        return 2
    except ValueError as exc:
        reason = exc.args[0] if exc.args else "unclassified"
        if reason not in ("invalid_date", "invalid_money",
                          "incomplete_openai_credit_snapshot"):
            reason = "unclassified"
        print("PROVIDER_BILLING_WATCH=CONFIG_BLOCKED_" + str(reason).upper())
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

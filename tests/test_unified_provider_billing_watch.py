"""Offline checks for unified DeepSeek and AWS cost evidence (no real API calls)."""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
import json
from pathlib import Path

import pytest

from scripts import aws_provider_billing_cost as aws
from scripts import provider_billing_renewal_watch as watch

NOW = datetime(2026, 10, 15, 7, 30, tzinfo=timezone.utc)


def _sample(amount="3.25", estimated=True):
    return json.dumps({"ResultsByTime": [{
        "TimePeriod": {"Start": "2026-10-01", "End": "2026-10-16"},
        "Estimated": estimated,
        "Total": {"UnblendedCost": {"Amount": amount, "Unit": "USD"}},
        "Groups": [],
    }]}).encode()


def test_aws_cost_explorer_reads_exactly_one_month_and_never_changes_resources():
    seen = []

    def fake_cli(args, capture_output, check, timeout):
        seen.append(args)
        assert capture_output and not check and timeout == 18
        return SimpleNamespace(returncode=0, stdout=_sample(), stderr=b"secret")

    assert aws.aws_cost_mtd(NOW, runner=fake_cli) == ("OK", "3.25", True)
    cmd = seen[0]
    assert cmd[:3] == ["aws", "ce", "get-cost-and-usage"]
    assert "Start=2026-10-01,End=2026-10-16" in cmd
    assert "MONTHLY" in cmd and "UnblendedCost" in cmd
    assert not any(x in cmd for x in ("put", "delete", "create", "update"))


@pytest.mark.parametrize("body", [
    b"", b"hello", b"{}", b"[]" * 70000,
    json.dumps({"ResultsByTime": []}).encode(),
    _sample("-2"), _sample("NaN"), _sample("Infinity"),
    _sample("1e500"), _sample("1000000000"),
    _sample().replace(b'"USD"', b'"CNY"'),
    _sample().replace(b'"Estimated": true', b'"Estimated": null'),
])
def test_aws_cost_bad_data_rejected_without_guessing_balance(body):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        aws.parse_monthly_cost(body)


def test_aws_access_denied_fails_unknown_safely():
    def denied(*_args, **_kwargs):
        return SimpleNamespace(returncode=254, stdout=b"", stderr=b"ACCOUNT_ID SECRET")
    assert aws.aws_cost_mtd(NOW, runner=denied) == (
        "NOT_AUTHORIZED_OR_UNAVAILABLE", None, None
    )


def test_unified_provider_contains_deepseek_actual_wallet_status_and_aws_spend():
    env = {
        "DEEPSEEK_API_KEY": "fake",
        "AWS_COST_STATUS": "OK", "AWS_COST_MTD_USD": "8.20",
        "AWS_COST_ESTIMATED": "true", "AWS_MONTHLY_BUDGET_USD": "10",
        "TICKFLOW_RENEWAL_DATE": "2026-10-22",
    }
    report, alerts = watch.evaluate(NOW, env=env,
        deepseek_fetch=lambda key: ("LOW", ["CNY", "USD"]))
    assert any("DeepSeek official wallet=LOW" in line for line in report)
    assert any("DeepSeek official wallet LOW" in line for line in alerts)
    assert any("AWS Cost Explorer MTD unblended spend $8.20" in line for line in report)
    assert any("AWS Cost Explorer MTD spend >=80%" in line for line in alerts)
    assert any("AWS prepaid credit/remaining actual balance=UNKNOWN" in line for line in report)
    assert any("TickFlow" in line for line in alerts)
    assert any("OpenD" in line for line in report)


def test_unified_realistic_dual_currency_wallet_ok_not_marked_empty():
    report, alerts = watch.evaluate(NOW,
       env={"DEEPSEEK_API_KEY": "dummy", "AWS_COST_STATUS": "UNKNOWN"},
       deepseek_fetch=lambda _: ("OK", ["CNY", "USD"]))
    assert any("DeepSeek official wallet=OK" in s for s in report)
    assert not any("DeepSeek" in x for x in alerts)
    assert any("AWS Cost Explorer=UNKNOWN" in x for x in report)


def test_deepseek_upstream_failure_never_reports_balance_is_zero():
    def fail(_):
        raise ValueError("http_503")
    report, alerts = watch.evaluate(NOW,
        env={"DEEPSEEK_API_KEY": "redacted"}, deepseek_fetch=fail)
    assert any("wallet=UNKNOWN" in x for x in report)
    assert not any("EMPTY" in a for a in alerts)
    assert not any("redacted" in x for x in report + alerts)


def test_non_numeric_or_partial_aws_evidence_fails_closed():
    for amount in ("NaN", "-1", "Infinity", ""):
        with pytest.raises(ValueError):
            watch.evaluate(NOW, env={
                "AWS_COST_STATUS": "OK",
                "AWS_COST_MTD_USD": amount,
                "AWS_COST_ESTIMATED": "true",
            })


def test_single_provider_schedule_and_separate_aws_oidc_identity():
    unified = Path(".github/workflows/provider-billing-renewal-watch.yml").read_text()
    standalone = Path(".github/workflows/engineering-autonomy-deepseek-balance-watch.yml").read_text()
    assert "cron: '20 1 * * *'" in unified
    assert "schedule:" not in standalone
    assert "workflow_dispatch:" in standalone
    assert "DEEPSEEK_API_KEY: \${{ secrets.DEEPSEEK_API_KEY }}" in unified
    assert "AWS_MONTHLY_BUDGET_USD: \${{ vars.AWS_MONTHLY_BUDGET_USD }}" in unified
    assert "aws-cost:" in unified and "id-token: write" in unified
    assert "python3 scripts/aws_provider_billing_cost.py" in unified
    assert "aws-actions/configure-aws-credentials@v4" in unified
    assert "status: \${{ steps.cost.outputs.status || steps.unavailable.outputs.status }}" in unified
    before, after = unified.split("  watch:", 1)
    assert "OPENAI_ADMIN_KEY" not in before
    assert "DEEPSEEK_API_KEY" not in before
    assert "role-to-assume:" not in after
    assert "dry_run" in unified and "inputs.dry_run == false" in before

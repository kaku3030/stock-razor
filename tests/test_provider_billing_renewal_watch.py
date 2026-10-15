"""Offline contract tests for the cloud-only billing/renewal watch."""
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
import pytest

from scripts.provider_billing_renewal_watch import (
    COSTS, USAGE, _get_json, completion_tokens, cost_usd, evaluate,
    renewal_alert, positive_money, utc_date, discord_send,
)
NOW=datetime(2026,10,15,4,30,tzinfo=timezone.utc)


def sample(path, key, start, end):
    assert key == "fake-admin-credential"
    assert 0 < start < end
    if path == COSTS:
        return {"data": [{"results":[{"amount":{"currency":"usd","value":1.2}}]}],"has_more":False}
    if path == USAGE:
        return {"data":[{"results":[{"num_model_requests":17,"input_tokens":3900,
                                    "output_tokens":1200}]}],"has_more":False}
    raise AssertionError("unexpected API path")


def test_openai_mtd_and_approx_not_actual_balance():
    report, alerts=evaluate(NOW,env={"OPENAI_ADMIN_KEY":"fake-admin-credential",
            "OPENAI_MONTHLY_BUDGET_USD":"5",
            "OPENAI_CREDIT_SNAPSHOT_USD":"2.50",
            "OPENAI_CREDIT_SNAPSHOT_DATE_UTC":"2026-10-01",
            "TICKFLOW_RENEWAL_DATE":"2026-10-22"},fetch=sample)
    assert any("MTD spend $1.20" in line for line in report)
    assert any("requests 17" in line for line in report)
    assert any("PREPAID ESTIMATE" in line for line in report)
    assert any("exact prepaid balance=UNKNOWN" in line for line in report)
    assert any("estimated prepaid credit" in line for line in alerts)
    assert any("in 7d" in line for line in alerts)


def test_openai_missing_key_does_not_guess_balance_or_usage():
    report, alerts=evaluate(NOW, env={},fetch=lambda *args: (_ for _ in ()).throw(
        AssertionError("must not call")))
    assert any("usage/cost=UNKNOWN" in line for line in report)
    assert any("renewal=UNKNOWN" in line for line in report)
    assert not alerts  # Thursday; weekly config notices on Monday only


@pytest.mark.parametrize("days", [30,14,7,3,1,0])
def test_renewal_exact_warning_days(days):
    t=date(2026,10,15)
    assert "TickFlow" in renewal_alert(t+timedelta(days=days), t)
    assert renewal_alert(t+timedelta(days=8),t) is None


def test_negative_and_invalid_bill_data_fail_closed():
    for v in ("NaN","Infinity","-2",True):
        with pytest.raises(ValueError):
            positive_money(v)
    with pytest.raises(ValueError):
        cost_usd({"data":[{"results":[{"amount":{"currency":"jpy","value":1}}]}]})
    with pytest.raises(ValueError):
        completion_tokens({"data":[{"results":[{"num_model_requests":-1,
                        "input_tokens":1,"output_tokens":1}]}]})
    with pytest.raises(ValueError):
        utc_date("2026-02-30")


def test_partial_openai_api_data_never_reports_false_usage():
    def truncated(path,*args):
        obj=sample(path,*args)
        if path == COSTS:
            obj["has_more"]=True
            # mimics _get_json contract failing on incomplete page
            raise ValueError("incomplete_page")
        return obj
    report,alerts=evaluate(NOW,env={"OPENAI_ADMIN_KEY":"fake-admin-credential"},
                             fetch=truncated)
    assert any("usage/cost=UNKNOWN" in line for line in report)
    assert alerts


def test_request_discord_stays_on_approved_host(monkeypatch):
    with pytest.raises(ValueError,match="invalid_discord_endpoint"):
        discord_send("https://evil.example/other","payload")
    with pytest.raises(ValueError):
        evaluate(NOW,env={"OPENAI_CREDIT_SNAPSHOT_USD":"5"})


def test_dry_run_no_vendor_calls_or_secrets():
    report,alerts=evaluate(NOW,env={"TICKFLOW_RENEWAL_DATE":"2026-10-15"})
    assert not any("fake-admin-credential" in line for line in report)
    assert any("TickFlow" in a for a in alerts)


def test_explicit_manual_report_does_not_require_provider_key():
    """Manual send-report is opt-in; missing Admin key never invokes Costs API."""
    report, alerts = evaluate(NOW, env={}, fetch=lambda *_:
                              (_ for _ in ()).throw(AssertionError("no admin")))
    assert any("exact prepaid balance=UNKNOWN" in s for s in report)
    assert not alerts


def test_error_classification_does_not_serialize_provider_body():
    from scripts.provider_billing_renewal_watch import _get_json
    # Protected internal routine must reject arbitrarily chosen exfil domains.
    with pytest.raises(ValueError, match="invalid_endpoint_or_key"):
        _get_json("https://untrusted.example/", "dummy", 1, 2)


def test_webhook_fallback_after_safe_first_failure(monkeypatch, capsys):
    import sys
    from scripts import provider_billing_renewal_watch as watch
    called=[]
    def send(webhook, content):
        called.append(webhook)
        if webhook == "https://discord.com/api/webhooks/failing":
            raise ValueError("discord_delivery_failed")
    monkeypatch.setattr(watch, "discord_send", send)
    monkeypatch.setattr(sys, "argv", ["watch", "--send-report"])
    monkeypatch.setenv("DISCORD_RADAR_WEBHOOK_URL",
                       "https://discord.com/api/webhooks/failing")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL",
                       "https://discord.com/api/webhooks/fallback")
    monkeypatch.delenv("OPENAI_ADMIN_KEY", raising=False)
    monkeypatch.delenv("TICKFLOW_RENEWAL_DATE", raising=False)
    assert watch.main()==0
    out=capsys.readouterr().out
    assert "WEBHOOK_REJECTED_1_DISCORD_DELIVERY_FAILED" in out
    assert "WEEKLY_REPORT_DISPATCHED" in out
    assert called == ["https://discord.com/api/webhooks/failing",
                      "https://discord.com/api/webhooks/fallback"]

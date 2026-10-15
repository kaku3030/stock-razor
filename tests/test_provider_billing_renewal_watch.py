"""Offline contract tests for the cloud-only billing/renewal watch."""
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal
import pytest
import urllib.parse
import urllib.request

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


@pytest.mark.parametrize("path", [COSTS, USAGE])
def test_admin_request_uses_supported_daily_bucket_limit(monkeypatch, path):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"data":[],"has_more":false}'

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert _get_json(path, "fake-admin-credential", 1, 2) == {
        "data": [], "has_more": False
    }
    query = urllib.parse.parse_qs(urllib.parse.urlparse(requests[0][0].full_url).query)
    assert query["limit"] == ["31"]


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


def test_no_webhook_or_invalid_renewal_is_fail_closed(monkeypatch,capsys):
    from scripts import provider_billing_renewal_watch as watch
    monkeypatch.setattr(watch,"discord_send",lambda *a: (_ for _ in ()).throw(
        ValueError("discord_delivery_failed")))
    monkeypatch.setattr(watch,"datetime",type("Clock",(),{
        "now":staticmethod(lambda *_: NOW),
    }))
    monkeypatch.setattr(watch,"os",type("Environ",(),{
        "environ":{"DISCORD_RADAR_WEBHOOK_URL":"https://discord.com/api/webhooks/redacted"}
    }))
    monkeypatch.setattr(watch,"argparse",__import__("argparse"))
    monkeypatch.setattr(__import__("sys"),"argv",["watch","--send-report"])
    assert watch.main()==2
    assert "PROVIDER_BILLING_WATCH=DISCORD_DELIVERY_FAILED" in capsys.readouterr().out


def test_discord_backup_is_only_used_after_primary_failure(monkeypatch,capsys):
    from scripts import provider_billing_renewal_watch as watch
    calls = []
    def fake_send(hook, content):
        calls.append(hook)
        assert "exact prepaid balance=UNKNOWN" in content
        if hook.endswith("/primary"):
            raise ValueError("discord_http_404")
    monkeypatch.setattr(watch,"discord_send",fake_send)
    monkeypatch.setattr(watch,"datetime",type("Clock",(),{
        "now":staticmethod(lambda *_: NOW),
    }))
    monkeypatch.setattr(watch,"os",type("Environ",(),{
        "environ":{
            "DISCORD_RADAR_WEBHOOK_URL":"https://discord.com/api/webhooks/primary",
            "DISCORD_WEBHOOK_URL":"https://discord.com/api/webhooks/backup",
        },
    }))
    monkeypatch.setattr(__import__("sys"),"argv",["watch","--send-report"])
    assert watch.main()==0
    assert calls==["https://discord.com/api/webhooks/primary",
                   "https://discord.com/api/webhooks/backup"]
    assert "DISCORD_FALLBACK_DISPATCHED" in capsys.readouterr().out


def test_discord_http_error_never_logs_body_or_webhook(monkeypatch):
    import io
    import urllib.error
    from scripts import provider_billing_renewal_watch as watch
    def fake_urlopen(*_args,**_kwargs):
        raise urllib.error.HTTPError(
            "https://discord.com/api/webhooks/SENSITIVE",
            404, "SENSITIVE_BODY", None, io.BytesIO(b"SENSITIVE_BODY")
        )
    monkeypatch.setattr(watch.urllib.request,"urlopen",fake_urlopen)
    with pytest.raises(ValueError,match="discord_http_404") as err:
        watch.discord_send("https://discord.com/api/webhooks/123/secret","hi")
    assert "SENSITIVE" not in str(err.value)


def test_telegram_owner_fallback_after_both_discord_webhooks_fail(monkeypatch,capsys):
    from scripts import provider_billing_renewal_watch as watch
    discord_calls=[]
    telegram_calls=[]
    def fake_discord(url, content):
        discord_calls.append(url)
        raise ValueError("discord_http_403")
    def fake_telegram(token,chat,content):
        telegram_calls.append((token,chat))
        assert "balance=UNKNOWN" in content
    monkeypatch.setattr(watch,"discord_send",fake_discord)
    monkeypatch.setattr(watch,"telegram_send",fake_telegram)
    monkeypatch.setattr(watch,"datetime",type("Clock",(),{
        "now":staticmethod(lambda *_: NOW),
    }))
    monkeypatch.setattr(watch,"os",type("Environ",(),{"environ":{
        "DISCORD_RADAR_WEBHOOK_URL":"https://discord.com/api/webhooks/primary",
        "DISCORD_WEBHOOK_URL":"https://discord.com/api/webhooks/backup",
        "TELEGRAM_BOT_TOKEN":"123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "TELEGRAM_CHAT_ID":"-1001234567890",
    }}))
    monkeypatch.setattr(__import__("sys"),"argv",["watch","--send-report"])
    assert watch.main()==0
    assert len(discord_calls)==2
    assert telegram_calls==[("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ","-1001234567890")]
    assert "TELEGRAM_FALLBACK_DISPATCHED" in capsys.readouterr().out


def test_telegram_bad_destination_stays_fail_closed(monkeypatch):
    from scripts import provider_billing_renewal_watch as watch
    with pytest.raises(ValueError,match="invalid_telegram_config"):
        watch.telegram_send("fake-token","anything","safe")


def test_standard_user_agent_and_telegram_http_no_error_body_leak(monkeypatch):
    import io
    import urllib.error
    from scripts import provider_billing_renewal_watch as watch
    headers = []
    def fake_urlopen(request, **kwargs):
        headers.append(dict(request.header_items()))
        raise urllib.error.HTTPError(
            "https://api.telegram.org/botSENSITIVE_TOKEN/sendMessage",
            403, "SENSITIVE_ERROR", None, io.BytesIO(b"SENSITIVE_ERROR"),
        )
    monkeypatch.setattr(watch.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ValueError, match="telegram_http_403") as err:
        watch.telegram_send("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ", "-1001234567890", "hello")
    assert "SENSITIVE" not in str(err.value)
    assert headers[0]["User-agent"] == "StockRazor-ProviderWatch/1.0"


def test_cloud_workflow_uses_module_entrypoint_for_repo_root_imports():
    """The cloud runner must not load the script as an isolated sys.path entry."""
    from pathlib import Path
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/provider-billing-renewal-watch.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("python3 -m scripts.provider_billing_renewal_watch") == 3
    assert "python3 scripts/provider_billing_renewal_watch.py" not in workflow

    # Executed in a child process so a missing repo-root package import cannot
    # be disguised by pytest's own sys.path.
    result = subprocess.run(
        [sys.executable, "-m", "scripts.provider_billing_renewal_watch", "--dry-run"],
        cwd=root, text=True, capture_output=True, timeout=20, check=False,
    )
    assert result.returncode == 0
    assert "PROVIDER_BILLING_WATCH=DRY_RUN_PASS" in result.stdout

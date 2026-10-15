"""Provider-free DeepSeek balance, token telemetry, and recharge alert tests."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from engineering_autonomy import deepseek_budget as b
from engineering_autonomy import deepseek_budget_issue as alerts


def balance(cny="110.00", usd=None, available=True):
    infos = [
        {"currency": "CNY", "total_balance": cny,
         "granted_balance": "0.00", "topped_up_balance": cny}
    ]
    if usd is not None:
        infos.append({"currency": "USD", "total_balance": usd,
                      "granted_balance": "0.00", "topped_up_balance": usd})
    return json.dumps({"is_available": available, "balance_infos": infos}).encode()


@pytest.mark.parametrize("body,expected", [
    (balance(), "OK"), (balance("10.00"), "LOW"),
    (balance("0.01"), "LOW"), (balance("0.00"), "EMPTY"),
    (balance("1.00", available=False), "UNAVAILABLE"),
    (balance("0.00", available=False), "EMPTY"),
    (balance("0.00", usd="2.50"), "OK"),
    (balance("0.00", usd="1.50"), "LOW"),
])
def test_balance_categories_and_mixed_currency_safeguard(body, expected):
    status, codes = b.classify_balance(body)
    assert status == expected
    assert codes == sorted(codes)


@pytest.mark.parametrize("body", [
    b"", b"{}", b"hello", b"[]" * 10000,
    json.dumps({"is_available": "true", "balance_infos": []}).encode(),
    json.dumps({"is_available": True, "balance_infos": []}).encode(),
    balance("-1"), balance("NaN"), balance("1e1000"), balance("10.000000000"),
    balance("1.00", usd="NaN"),
    json.dumps({"is_available": True, "balance_infos": [
        {"currency": "EUR", "total_balance": "10.00",
         "granted_balance": "0", "topped_up_balance": "10.00"}
    ]}).encode(),
])
def test_balance_malformed_or_unknown_not_equated_with_empty(body):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        b.classify_balance(body)


def test_balance_requests_only_official_get_and_never_completion(monkeypatch, tmp_path):
    seen = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, max_bytes):
            assert max_bytes == b.LIMIT_BYTES + 1
            return balance("12.00")

    def opener(req, timeout):
        seen.append((req.full_url, req.get_method(), timeout))
        assert req.headers["Authorization"] == "Bearer private-test-key"
        return FakeResponse()

    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-test-key")
    monkeypatch.setattr(b.urllib.request, "urlopen", opener)
    path = tmp_path / "balance.json"
    assert b.check_balance(path) == 0
    assert seen == [("https://api.deepseek.com/user/balance", "GET", 12)]
    data = path.read_text()
    assert "private-test-key" not in data
    assert "12.00" not in data
    assert b.read_status(path) == "OK"


@pytest.mark.parametrize("amount,gate_code,monitor_code", [
    ("12.00", 0, 0), ("5.00", 2, 0), ("0.00", 2, 0)
])
def test_gates_block_paid_code_but_allow_low_balance_notification(
    monkeypatch, tmp_path, amount, gate_code, monitor_code
):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test")
    monkeypatch.setattr(b, "fetch_balance",
                        lambda _: b.classify_balance(balance(amount)))
    path = tmp_path / "status.json"
    assert b.check_balance(path) == gate_code
    assert b.check_balance(path, monitor=True) == monitor_code


def test_provider_errors_fail_closed_not_mislabeled_as_zero(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    path = tmp_path / "unknown.json"
    assert b.check_balance(path, monitor=True) == 2
    assert b.read_status(path) == "UNKNOWN"


def test_aider_raw_analytics_whitelisted_into_token_counters(tmp_path, monkeypatch):
    f = tmp_path / "unsafe-full-analytics.jsonl"
    events = [
        {"event": "launched", "properties": {"prompt": "NEVER LOG ME"}},
        {"event": "message_send", "user_id": "sensitive_uuid", "properties": {
            "main_model": "deepseek/deepseek-flash", "prompt_tokens": 120,
            "completion_tokens": 33, "total_tokens": 153, "cost": 0.002,
            "prompt": "private code must not leak"}},
        {"event": "message_send", "properties": {
            "prompt_tokens": 80, "completion_tokens": 17,
            "total_tokens": 97, "cost": 0.001}},
    ]
    f.write_text("\n".join(json.dumps(x) for x in events) + "\n")
    result = b.summarize_usage(f)
    assert result == {
        "status": "OBSERVED", "requests": 2, "input_tokens": 200,
        "output_tokens": 50, "total_tokens": 250, "estimated_cost_usd": "0.003000"
    }
    output = tmp_path / "telemetry.json"
    step = tmp_path / "gha-summary.md"
    monkeypatch.setenv("GITHUB_RUN_ID", "12345")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    assert b.usage_command(f, output) == 0
    contents = output.read_text() + step.read_text()
    assert "250" in contents
    for secret in ("sensitive_uuid", "NEVER LOG ME", "private code must not leak"):
        assert secret not in contents
    assert json.loads(output.read_text())["run_id"] == "12345"


def test_missing_or_invalid_analytics_is_unknown_not_fake_zero(tmp_path):
    assert b.summarize_usage(tmp_path / "missing.jsonl") == {
        "status": "NO_DATA", "requests": 0,
    }
    f = tmp_path / "aider.jsonl"
    f.write_text(json.dumps({"event": "message_send", "properties": {
        "prompt_tokens": -1, "completion_tokens": 2}}))
    assert b.summarize_usage(f)["status"] == "UNVERIFIED"


def test_alert_create_dedupe_update_recovery_and_unknown(monkeypatch):
    calls = []
    open_issues = []

    def fake_gh(*args):
        calls.append(args)
        if args[0:2] == ("issue", "list"):
            return json.dumps(open_issues)
        if args[0:2] == ("issue", "create"):
            body = args[args.index("--body") + 1]
            open_issues.append({"number": 77, "title": b.ISSUE_TITLE, "body": body})
            return "url"
        if args[0:2] == ("issue", "edit"):
            open_issues[0]["body"] = args[args.index("--body") + 1]
        if args[0:2] == ("issue", "close"):
            open_issues.clear()
        return "ok"

    monkeypatch.setattr(alerts, "gh", fake_gh)
    repo = "kaku3030/stock-razor"
    assert alerts.reconcile_status("LOW", repo, "kaku3030") == "ALERT_CREATED"
    assert alerts.reconcile_status("LOW", repo, "kaku3030") == "ALERT_ALREADY_OPEN"
    assert len([x for x in calls if x[:2] == ("issue", "create")]) == 1
    assert alerts.reconcile_status("EMPTY", repo, "kaku3030") == "ALERT_UPDATED"
    assert len([x for x in calls if x[:2] == ("issue", "comment")]) == 1
    count = len(calls)
    assert alerts.reconcile_status("UNKNOWN", repo, "kaku3030") == "UNKNOWN_NO_BALANCE_CLAIM"
    assert len(calls) == count
    assert alerts.reconcile_status("OK", repo, "kaku3030") == "RECOVERED_CLOSED"
    assert not open_issues


def test_workflow_separates_balance_secrets_and_github_issue_authorization():
    path = Path(".github/workflows/engineering-autonomy-deepseek-balance-watch.yml")
    watch = path.read_text(encoding="utf-8")
    assert "cron: '17 */6 * * *'" in watch
    assert "issues: write" in watch
    assert "persist-credentials: false" in watch
    assert watch.count("python -m engineering_autonomy.deepseek_budget check") == 1
    assert "python -m engineering_autonomy.deepseek_budget_issue" in watch
    notify = watch.split("- name: Reconcile one GitHub recharge alert", 1)[1]
    assert "secrets.DEEPSEEK_API_KEY" not in notify
    assert "gh pr merge" not in watch and "aider " not in watch
    coding = Path(".github/workflows/engineering-autonomy-coding-v1-1.yml").read_text()
    guard = coding.index("Enforce official DeepSeek balance budget")
    api_probe = coding.index("Block coding if DeepSeek provider API is unhealthy")
    coder = coding.index("Run isolated DeepSeek coding agent")
    assert guard < api_probe < coder
    assert '--analytics-log "$RUNNER_TEMP/autonomy-aider-usage.jsonl"' in coding
    assert "--no-analytics" in coding
    assert "Retain sanitized token counters only" in coding
    assert "retention-days: 30" in coding
    assert "steps.budget.outcome == 'success'" in coding
    assert "schedule:" not in coding
    assert "gh pr merge" not in coding

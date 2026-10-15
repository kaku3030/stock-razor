"""Provider-free DeepSeek balance, token telemetry, and recharge alert tests."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

from engineering_autonomy import deepseek_budget as b
from engineering_autonomy import deepseek_budget_discord as alerts


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


def test_discord_alert_payload_only_categorical_not_balance_or_secret():
    url = "https://discord.com/api/webhooks/123456789012345678/abcDEF01234567890123"
    seen = []

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def fake_open(req, timeout):
        assert req.get_method() == "POST"
        assert timeout == 12
        seen.append(req.data.decode("utf-8"))
        return FakeResponse()

    assert alerts.send_discord("LOW", url, opener=fake_open) == "ALERT_SENT"
    assert alerts.send_discord(
        "EMPTY", url, "987654321012345678", opener=fake_open
    ) == "ALERT_SENT"
    first, second = (json.loads(x) for x in seen)
    assert first["allowed_mentions"] == {"parse": []}
    assert second["allowed_mentions"] == {
        "parse": [], "users": ["987654321012345678"]
    }
    assert "<@987654321012345678>" in second["content"]
    assert "充值" in second["content"]
    for payload in seen:
        assert "DEEPSEEK_API_KEY" not in payload
        assert "total_balance" not in payload
        assert url not in payload


def test_discord_reminder_handles_healthy_unknown_and_missing_channel():
    assert alerts.send_discord("OK", "") == "HEALTHY_NO_ALERT"
    assert alerts.send_discord("LOW", "") == "CHANNEL_NOT_CONFIGURED"
    assert "不代表余额为零" in alerts.message_for_status("UNKNOWN")
    with pytest.raises(ValueError):
        alerts.send_discord(
            "LOW", "https://evil.example/api/webhooks/123456789012345678/abcDEF01234567890123"
        )


def test_workflow_separates_balance_secrets_and_discord_notification():
    path = Path(".github/workflows/engineering-autonomy-deepseek-balance-watch.yml")
    watch = path.read_text(encoding="utf-8")
    assert "cron: '17 */12 * * *'" in watch
    assert "issues: write" not in watch
    assert "contents: read" in watch
    assert "persist-credentials: false" in watch
    assert watch.count("python -m engineering_autonomy.deepseek_budget check") == 1
    assert "python -m engineering_autonomy.deepseek_budget_discord" in watch
    notify = watch.split("- name: Notify DeepSeek recharge state through Discord", 1)[1]
    assert "secrets.DEEPSEEK_API_KEY" not in notify
    assert "secrets.DISCORD_WEBHOOK_URL" in notify
    assert "secrets.STOCK_RAZOR_DISCORD_WEBHOOK_URL" not in notify
    assert "secrets.DISCORD_RADAR_WEBHOOK_URL" not in notify
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


def test_discord_manual_delivery_uses_existing_secret(monkeypatch, capsys):
    """Manually requested test must never imply low balance or leak URLs."""
    import sys

    webhook = "https://discord.com/api/webhooks/123456789012345678/abcDEF01234567890123"
    seen = []

    def fake_send(status, url, user_id):
        seen.append((status, url, user_id))
        return "ALERT_SENT"

    monkeypatch.setattr(alerts, "send_discord", fake_send)
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", webhook)
    monkeypatch.setenv("STOCK_RAZOR_DISCORD_USER_ID", "")
    monkeypatch.setenv("STOCK_RAZOR_DISCORD_WEBHOOK_URL", "wrong-legacy-value")
    monkeypatch.setattr(sys, "argv", ["deepseek_budget_discord", "--test-delivery"])
    assert alerts.main() == 0
    assert seen == [("TEST", webhook, "")]
    output = capsys.readouterr().out
    assert "BUDGET_ALERT=ALERT_SENT" in output
    assert webhook not in output

    msg = alerts.message_for_status("TEST")
    assert "测试" in msg
    assert "无需充值" in msg
    assert "余额已耗尽" not in msg


def test_manual_discord_delivery_remains_opt_in_and_scheduled_balance_only():
    workflow = Path(".github/workflows/engineering-autonomy-deepseek-balance-watch.yml").read_text(
        encoding="utf-8"
    )
    assert "test_discord_delivery:" in workflow
    assert "default: false" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.test_discord_delivery == true" in workflow
    assert workflow.count("python -m engineering_autonomy.deepseek_budget_discord --test-delivery") == 1
    assert "DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}" in workflow
    assert "STOCK_RAZOR_DISCORD_WEBHOOK_URL" not in workflow
    assert "secrets.DEEPSEEK_API_KEY" not in workflow.split(
        "- name: Send one explicitly requested Discord delivery test", 1
    )[1]
    assert "gh pr merge" not in workflow

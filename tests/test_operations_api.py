from api.v1.endpoints.operations import operations_status


def test_operations_status_is_fail_closed(monkeypatch):
    for key in (
        "RADAR_ADMISSION",
        "SOURCE_ARBITER_ADMISSION",
        "PAPER_AUTO_READY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "DISCORD_RADAR_WEBHOOK_URL",
        "NOTIFICATION_REPORT_CHANNELS",
        "NOTIFICATION_ALERT_CHANNELS",
        "NOTIFICATION_SYSTEM_ERROR_CHANNELS",
    ):
        monkeypatch.delenv(key, raising=False)

    response = operations_status()

    assert response.mode == "research_only"
    assert response.radar_admission == "BLOCKED"
    assert response.source_arbiter_admission == "BLOCKED"
    assert response.live_trade is False
    assert response.paper_auto_ready is False
    assert response.paper_engine_status == "IMPLEMENTED_OFFLINE_ONLY"
    assert response.paper_runtime_api_status == "NOT_EXPOSED"
    assert response.notification_ready is False
    assert response.notification_routes == {"report": [], "alert": [], "system_error": []}
    assert response.notification_delivery_evidence == "NOT_VERIFIED"
    assert "真实手机接收回执" in response.pending_acceptance


def test_operations_status_reports_configured_notification_channel(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")

    response = operations_status()

    assert response.notification_channels_configured == ["telegram"]
    assert response.notification_ready is True
    # A configured webhook is not proof that the phone received a message.
    assert "真实手机接收回执" in response.pending_acceptance
    assert response.live_trade is False


def test_operations_status_reports_radar_discord_webhook(monkeypatch):
    for key in (
        "DISCORD_WEBHOOK_URL",
        "DISCORD_BOT_TOKEN",
        "DISCORD_MAIN_CHANNEL_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DISCORD_RADAR_WEBHOOK_URL", "https://discord.example/radar")

    response = operations_status()

    assert response.notification_channels_configured == ["discord"]
    assert response.notification_ready is True
    assert response.live_trade is False


def test_operations_status_reports_effective_notification_routes(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")
    monkeypatch.setenv("DISCORD_RADAR_WEBHOOK_URL", "https://discord.example/radar")
    monkeypatch.setenv("NOTIFICATION_REPORT_CHANNELS", "telegram")
    monkeypatch.setenv("NOTIFICATION_ALERT_CHANNELS", "discord")

    response = operations_status()

    assert response.notification_routes["report"] == ["telegram"]
    assert response.notification_routes["alert"] == ["discord"]
    assert response.notification_routes["system_error"] == ["telegram", "discord"]
    assert response.notification_delivery_evidence == "NOT_VERIFIED"


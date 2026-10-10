from api.v1.endpoints.operations import operations_status


def test_operations_status_is_fail_closed(monkeypatch):
    for key in (
        "RADAR_ADMISSION",
        "SOURCE_ARBITER_ADMISSION",
        "PAPER_AUTO_READY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    response = operations_status()

    assert response.mode == "research_only"
    assert response.radar_admission == "BLOCKED"
    assert response.source_arbiter_admission == "BLOCKED"
    assert response.live_trade is False
    assert response.paper_auto_ready is False
    assert response.notification_ready is False
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


from src.services.stock_radar_v2.notifications import RadarNotifier
from src.services.stock_radar_v2.runtime_notifications import NotificationServiceRadarSink


class FakeNotificationService:
    def __init__(self) -> None:
        self.calls = []

    def send_with_results(self, content, **kwargs):
        self.calls.append((content, kwargs))
        return ["sent"]


def test_runtime_sink_uses_existing_alert_route_and_research_only_payload() -> None:
    service = FakeNotificationService()
    sink = NotificationServiceRadarSink(service)

    RadarNotifier(sink).notify(
        "signal_qa_alert",
        {"signal_type": "breakout", "review_id": "review-1", "failure_count": 7},
    )

    content, kwargs = service.calls[0]
    assert kwargs["route_type"] == "alert"
    assert kwargs["severity"] == "warning"
    assert kwargs["dedup_key"] == "stock_radar_v2:signal_qa_alert:breakout:7"
    assert kwargs["cooldown_key"] == "stock_radar_v2:signal_qa_alert:breakout:warning"
    assert kwargs["structured_payload"]["research_only"] is True
    assert "不是买卖建议或交易指令" in content


def test_critical_health_event_maps_to_critical_severity() -> None:
    service = FakeNotificationService()
    RadarNotifier(NotificationServiceRadarSink(service)).notify(
        "data_health_alert",
        {"provider": "primary", "reason": "authentication_error"},
    )

    assert service.calls[0][1]["severity"] == "critical"


def test_runtime_sink_is_fail_open_when_notification_service_raises() -> None:
    class BrokenNotificationService:
        def send_with_results(self, content, **kwargs):
            raise RuntimeError("channel unavailable")

    sink = NotificationServiceRadarSink(BrokenNotificationService())

    RadarNotifier(sink).notify("provider_fallback_alert", {"provider": "primary"})

    assert sink.last_error == "RuntimeError"


def test_runtime_sink_sanitizes_untrusted_event_payload_before_text_and_route() -> None:
    service = FakeNotificationService()
    sink = NotificationServiceRadarSink(service)
    RadarNotifier(sink).notify("data_health_alert", {
        "provider": "OpenD",
        "reason": "provider disconnected",
        "api_key": "secret-from-provider",
        "account_id": "123456",
        "password": "top-secret",
        "details": {"authorization": "Bearer leaked"},
        "positions": [{"symbol": "US.AMD", "shares": 100}],
        "error_code": "TOKEN=never-print-this",
        "review_id": "review-2",
    })
    content, kwargs = service.calls[0]
    projected = kwargs["structured_payload"]["payload"]
    assert projected["reason"] == "provider disconnected"
    assert projected["provider"] == "OpenD"
    assert projected["error_code"] == "[REDACTED]"
    assert projected["review_id"] == "review-2"
    for forbidden in (
        "secret-from-provider", "top-secret", "123456",
        "Bearer leaked", "US.AMD", "never-print-this",
    ):
        assert forbidden not in content
        assert forbidden not in str(kwargs)
    assert "api_key" not in projected
    assert "positions" not in projected
    assert "account_id" not in projected
    assert kwargs["dedup_key"] == "stock_radar_v2:data_health_alert:OpenD:provider disconnected"


def test_notification_formatter_bounds_large_and_multiline_untrusted_strings() -> None:
    service = FakeNotificationService()
    sink = NotificationServiceRadarSink(service)
    RadarNotifier(sink).notify("signal_qa_alert", {
        "signal_type": "breakout",
        "reason": "https://private-provider.example.com?auth=secret",
        "signal_id": "A" * 200,
        "severity": "warning",
        "review_id": "note\nFAKE ALERT HEADER",
        "risk_gate": ["BLOCKED", {"secret": "hidden"}],
    })
    text, kwargs = service.calls[0]
    assert "https://private-provider" not in text
    assert "FAKE ALERT HEADER" not in text
    assert "A" * 200 not in text
    assert "hidden" not in str(kwargs)
    assert kwargs["structured_payload"]["payload"]["reason"] == "[REDACTED]"
    assert kwargs["structured_payload"]["payload"]["signal_id"] == "[REDACTED]"
    assert "risk_gate" not in kwargs["structured_payload"]["payload"]


def test_transport_exceptions_never_log_sensitive_content(caplog) -> None:
    class TokenErrorService:
        def send_with_results(self, content, **kwargs):
            raise ValueError("Authorization Bearer MOST_SENSITIVE_TOKEN")

    service = TokenErrorService()
    sink = NotificationServiceRadarSink(service)
    with caplog.at_level("WARNING"):
        RadarNotifier(sink).notify("provider_fallback_alert", {"provider": "primary"})
    assert sink.last_error == "ValueError"
    assert "MOST_SENSITIVE_TOKEN" not in caplog.text

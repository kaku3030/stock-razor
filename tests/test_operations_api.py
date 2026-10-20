from api.v1.endpoints.operations import operations_status, paper_operator_controls, router


def test_us_live_monitor_requires_fresh_matching_source_identity(monkeypatch):
    import api.v1.endpoints.operations as operations

    monkeypatch.setattr(operations, "read_us_livefeed_health", lambda: {
        "status": "HEALTHY",
        "repo_sha": "a" * 40,
        "runtime_instance_id": "runtime-1",
        "realtime_delivery_evidence": True,
        "last_push_age_seconds": 2.0,
        "latest_push_status": "FRESH",
        "latest_push_observations": {
            "US.AMD": {
                "symbol": "US.AMD",
                "time_key": "2026-10-07 00:39:00",
                "close": 123.0,
                "volume": 12.0,
                "bar_closure": "UNPROVEN",
                "research_eligible": False,
                "private_field": "must not escape",
            },
        },
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "source_path": "C:/private/heartbeat.json",
    })
    monkeypatch.setattr(operations, "read_us_market_snapshots", lambda symbols: {
        "status": "PASS",
        "repo_sha": "a" * 40,
        "runtime_instance_id": "runtime-1",
        "symbols": {"US.AMD": {"latest": {"1m": {"close": 123.0}}}},
        "data_available": True,
        "radar_admission": "BLOCKED",
        "live_trade": False,
        "source_path": "C:/private/market.json",
    })

    response = operations.us_live_monitor()

    assert response.status == "REALTIME_SOURCE_EVIDENCE"
    assert response.source == "CLOUD_CANONICAL_OPEND_CACHE"
    assert response.source_identity_matched is True
    assert response.market["symbols"]["US.AMD"]["latest"]["1m"]["close"] == 123.0
    assert response.health["latest_push_observations"]["US.AMD"]["close"] == 123.0
    assert response.health["latest_push_observations"]["US.AMD"]["bar_closure"] == "UNPROVEN"
    assert response.health["latest_push_observations"]["US.AMD"]["research_eligible"] is False
    assert "private_field" not in response.health["latest_push_observations"]["US.AMD"]
    assert response.radar_admission == "BLOCKED"
    assert response.live_trade is False
    assert "source_path" not in response.health
    assert "source_path" not in response.market


def test_us_live_monitor_blocks_mismatched_runtime_identity(monkeypatch):
    import api.v1.endpoints.operations as operations

    monkeypatch.setattr(operations, "read_us_livefeed_health", lambda: {
        "status": "HEALTHY",
        "repo_sha": "a" * 40,
        "runtime_instance_id": "runtime-1",
        "realtime_delivery_evidence": True,
        "source_path": "C:/private/heartbeat.json",
    })
    monkeypatch.setattr(operations, "read_us_market_snapshots", lambda symbols: {
        "status": "PASS",
        "repo_sha": "a" * 40,
        "runtime_instance_id": "runtime-old",
        "symbols": {},
        "source_path": "C:/private/market.json",
    })

    response = operations.us_live_monitor()

    assert response.status == "BLOCKED_OR_STALE"
    assert response.source_identity_matched is False
    assert response.radar_admission == "BLOCKED"
    assert response.live_trade is False


def test_operations_status_is_fail_closed(monkeypatch):
    for key in (
        "RADAR_ADMISSION",
        "SOURCE_ARBITER_ADMISSION",
        "PAPER_AUTO_READY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "DISCORD_WEBHOOK_URL",
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
    assert response.execution_recovery_projection_status == "IMPLEMENTED_READ_ONLY_RUNTIME_WIRING_PENDING"
    assert response.paper_runtime_store_config_status == "NOT_CONFIGURED_OR_INVALID"
    assert response.external_simulator_contract_status == "READY_READ_ONLY_UNVERIFIED_CLOUD_ACCOUNT"
    assert response.simulated_account_evidence == "NOT_VERIFIED"
    assert response.notification_ready is False
    assert response.notification_routes == {"report": [], "alert": [], "system_error": []}
    assert response.notification_delivery_evidence == "NOT_VERIFIED"
    assert "��ʵ�ֻ����ջ�ִ" in response.pending_acceptance
    assert "�ƶ� OpenD SIMULATE �˻�ֻ������" in response.pending_acceptance


def test_operations_status_reports_configured_notification_channel(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DISCORD_RADAR_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")

    response = operations_status()

    assert response.notification_channels_configured == ["telegram"]
    assert response.notification_ready is False
    # A configured webhook is not proof that the phone received a message.
    assert "��ʵ�ֻ����ջ�ִ" in response.pending_acceptance
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
    assert response.notification_ready is False
    assert response.live_trade is False


def test_operations_status_reports_effective_notification_routes(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
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



def test_operations_status_reports_distinct_paper_store_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("PAPER_EXECUTION_STORE_PATH", str(tmp_path / "runtime.sqlite"))
    monkeypatch.setenv("PAPER_SHADOW_STORE_PATH", str(tmp_path / "shadow.sqlite"))

    response = operations_status()

    assert response.paper_runtime_store_config_status == "CONFIGURED_DISTINCT_DURABLE_PATHS"


def test_paper_controls_exposes_read_only_capabilities_only(monkeypatch):
    for key, value in (
        ("PAPER_AUTO_READY", "YES"),
        ("RADAR_ADMISSION", "PASS"),
        ("SOURCE_ARBITER_ADMISSION", "PASS"),
        ("LIVE_TRADE", "YES"),
    ):
        monkeypatch.setenv(key, value)

    response = paper_operator_controls()

    assert response.schema_version == "paper_operator_controls_v0_1"
    assert response.read_only is True
    assert response.mutation_allowed is False
    assert response.broker_io_allowed is False
    assert response.provider_io_allowed is False
    assert response.external_paper_account_evidence == "NOT_VERIFIED"
    assert response.phone_notification_receipt == "NOT_VERIFIED"
    actions = {action.action: action for action in response.actions}
    assert actions["inspect_operator_controls"].available is True
    assert all(
        not action.available
        for action in response.actions
        if action.action != "inspect_operator_controls"
    )
    # No POST/PATCH/DELETE on this router: even a permissive environment
    # cannot convert the operator disclosure interface into a trading API.
    assert all(route.methods == {"GET"} for route in router.routes)


def test_operator_response_cannot_claim_mutation_authority():
    from pydantic import ValidationError
    from api.v1.schemas.operations import PaperOperatorControlsResponse

    import pytest

    # Projection model defaults to fail-closed; implementation must never
    # obtain mutation authority via this informational endpoint.
    status = paper_operator_controls()
    assert status.model_dump()["mutation_allowed"] is False
    with pytest.raises(ValidationError):
        # Literal invariant is enforced by the schema.
        PaperOperatorControlsResponse(
            mutation_allowed=True,
            actions=[],
        )


def test_operations_status_never_promotes_unverified_external_paper_from_env(monkeypatch):
    # Env flags are requests, not qualification of a broker's account,
    # balance, open orders, fills or currently absent Paper operator API.
    for key in ("RADAR_ADMISSION", "SOURCE_ARBITER_ADMISSION", "PAPER_AUTO_READY", "LIVE_TRADE"):
        monkeypatch.setenv(key, "YES" if key.endswith(("READY", "TRADE")) else "PASS")

    status = operations_status()
    controls = paper_operator_controls()
    assert status.mode == "research_only"
    assert status.radar_admission == "BLOCKED"
    assert status.source_arbiter_admission == "BLOCKED"
    assert status.paper_auto_ready is False
    assert status.paper_runtime_api_status == "NOT_EXPOSED"
    assert status.simulated_account_evidence == "NOT_VERIFIED"
    assert status.live_trade is False
    assert controls.read_only is True
    assert controls.mutation_allowed is False
    assert controls.broker_io_allowed is False
    assert controls.external_paper_account_evidence == "NOT_VERIFIED"


def test_credentials_and_routes_never_count_as_verified_phone_receipt(monkeypatch):
    # A configured route can still have expired token, blocked account,
    # network outage, no active consumer or undelivered mobile notification.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")
    monkeypatch.setenv("DISCORD_RADAR_WEBHOOK_URL", "https://discord.example/hook")
    monkeypatch.setenv("NOTIFICATION_ALERT_CHANNELS", "telegram,discord")
    monkeypatch.setenv("NOTIFICATION_SYSTEM_ERROR_CHANNELS", "discord")
    monkeypatch.setenv("PAPER_AUTO_READY", "YES")

    response = operations_status()
    assert set(response.notification_channels_configured) >= {"telegram", "discord"}
    assert response.notification_routes["alert"] == ["telegram", "discord"]
    assert response.notification_delivery_evidence == "NOT_VERIFIED"
    assert response.notification_ready is False
    assert "��ʵ�ֻ����ջ�ִ" in response.pending_acceptance
    assert response.paper_auto_ready is False
    assert response.live_trade is False


def test_operation_effective_admission_ignores_permissive_env(monkeypatch):
    # A configuration value is never independently qualified source evidence.
    monkeypatch.setenv("RADAR_ADMISSION", "PASS")
    monkeypatch.setenv("SOURCE_ARBITER_ADMISSION", "PASS")
    monkeypatch.setenv("PAPER_AUTO_READY", "YES")
    monkeypatch.setenv("LIVE_TRADE", "YES")
    payload = operations_status()
    assert payload.mode == "research_only"
    assert payload.radar_admission == "BLOCKED"
    assert payload.source_arbiter_admission == "BLOCKED"
    assert payload.paper_auto_ready is False
    assert payload.live_trade is False


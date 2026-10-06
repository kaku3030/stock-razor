from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INSTALLER=(ROOT/"ops/aws/install_us_opend_livefeed.sh").read_text()
WORKFLOW=(ROOT/".github/workflows/deploy-us-opend-livefeed.yml").read_text()

def test_installer_is_read_only_and_fail_closed():
    assert "stock-razor-us-livefeed.service" in INSTALLER
    assert "FutuK1MStreamingAdapter" in INSTALLER
    assert "LiveFeedRuntimeBridge" in INSTALLER
    assert '"delivery_mode":"UNKNOWN"' in INSTALLER
    assert '"radar_admission":"BLOCKED"' in INSTALLER
    assert '"live_trade":False' in INSTALLER
    assert "OpenUSTradeContext" not in INSTALLER
    assert "OpenSecTradeContext" not in INSTALLER
    assert "adapter_diagnostics" in INSTALLER

def test_deploy_binds_exact_sha_and_requires_heartbeat():
    assert "REPO_REF=$REPO_REF" in WORKFLOW
    assert "us_opend_livefeed_heartbeat" in WORKFLOW
    assert '"event_count":[1-9][0-9]*' in WORKFLOW
    assert '"last_push_utc":"[^"]+"' in WORKFLOW
    assert '"live_trade":false' in WORKFLOW
    assert "US_OPEND_LIVEFEED_AWS_DEPLOYMENT=PASS" in WORKFLOW


def test_status_audit_is_read_only_and_covers_us_livefeed_runtime():
    ops = (ROOT/".github/workflows/aws-ssm-ops.yml").read_text()
    assert "- us_livefeed_status" in ops
    assert "stock-razor-us-livefeed.service" in ops
    assert "11111" in ops
    assert "/run/stock-razor-us-livefeed/latest-heartbeat.json" in ops
    assert "NRestarts" in ops
    assert 'cat "$status_path"' in ops
    assert "LIVE_TRADE=NO" in ops


def test_ssm_ops_has_canonical_adapter_standalone_readonly_probe():
    ops=(ROOT/".github/workflows/aws-ssm-ops.yml").read_text()
    assert "- us_opend_adapter_standalone_probe" in ops
    assert "FutuK1MStreamingAdapter" in ops
    assert '"radar_admission":"BLOCKED"' in ops
    assert '"live_trade":False' in ops
    assert "OpenUSTradeContext" not in ops


def test_ssm_ops_has_systemd_sandbox_adapter_probe():
    ops=(ROOT/".github/workflows/aws-ssm-ops.yml").read_text()
    assert "- us_opend_adapter_systemd_probe" in ops
    assert "systemd-run --wait --collect" in ops
    assert "NoNewPrivileges=true" in ops and "PrivateTmp=true" in ops and "ProtectSystem=strict" in ops
    assert "OpenUSTradeContext" not in ops


def test_ssm_ops_has_systemd_bridge_probe():
    ops=(ROOT/".github/workflows/aws-ssm-ops.yml").read_text()
    assert "- us_opend_bridge_systemd_probe" in ops
    assert "LiveFeedRuntimeBridge" in ops and "LiveFeedController" in ops
    assert "RADAR_ADMISSION=BLOCKED" in ops and "LIVE_TRADE=NO" in ops


def test_ssm_ops_has_persistent_loop_probe():
    ops=(ROOT/".github/workflows/aws-ssm-ops.yml").read_text()
    assert "- us_opend_persistent_loop_probe" in ops
    assert "for seq in range(1,7)" in ops and "bridge.drain()" in ops
    assert "RADAR_ADMISSION=BLOCKED" in ops and "LIVE_TRADE=NO" in ops


def test_ssm_ops_has_controlled_restart_probe():
    ops=(ROOT/".github/workflows/aws-ssm-ops.yml").read_text()
    assert "- us_livefeed_controlled_restart_probe" in ops
    assert "systemctl restart stock-razor-us-livefeed.service" in ops
    assert "sleep 15" in ops
    assert "RADAR_ADMISSION=BLOCKED" in ops and "LIVE_TRADE=NO" in ops


def test_ssm_ops_has_start_order_probe_with_recovery_trap():
    ops=(ROOT/".github/workflows/aws-ssm-ops.yml").read_text()
    assert "- us_opend_start_order_probe" in ops
    assert 'trap cleanup EXIT INT TERM' in ops
    assert 'systemctl stop "$svc"' in ops and 'systemctl start "$svc"' in ops
    assert "transient_while_persistent_stopped" in ops
    assert "RADAR_ADMISSION=BLOCKED" in ops and "LIVE_TRADE=NO" in ops

def test_installer_fails_closed_on_startup_callback_starvation():
    installer=(ROOT/"ops/aws/install_us_opend_livefeed.sh").read_text()
    assert "US_OPEND_STARTUP_CALLBACK_STARVATION" in installer
    assert "data_event_count == 0" in installer
    assert "if event_count == 0" not in installer
    assert "event.event_kind is ProviderEventKind.DATA" in installer
    assert '"event_count":data_event_count' in installer
    assert '"accepted_event_count":accepted_event_count' in installer
    assert "Restart=on-failure" in installer


def test_installer_enables_only_explicit_sync_transport_lifecycle_evidence():
    installer=(ROOT/"ops/aws/install_us_opend_livefeed.sh").read_text()
    assert 'OpenQuoteContext(host="127.0.0.1",port=11111)' in installer
    assert "OPEND_SYNC_CONTEXT_CONNECTED_EVIDENCE" in installer
    assert "futu-api 10.11.7108" in installer
    assert "_init_connect_sync() reports RET_OK" in installer
    assert '"delivery_mode":"UNKNOWN"' in installer
    assert '"radar_admission":"BLOCKED"' in installer
    assert '"live_trade":False' in installer

def test_deploy_gate_waits_for_bounded_self_heal_and_exact_sha():
    workflow=(ROOT/".github/workflows/deploy-us-opend-livefeed.yml").read_text()
    assert "verify_us_opend_livefeed.sh" in workflow
    assert "REPO_REF=$REPO_REF" in workflow
    assert "event_count" in workflow
    assert "sleep 5" in workflow

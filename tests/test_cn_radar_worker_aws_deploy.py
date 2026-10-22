from pathlib import Path


INSTALL = Path("ops/aws/install_cn_radar_worker.sh").read_text(encoding="utf-8")
VERIFY = Path("ops/aws/verify_cn_radar_worker.sh").read_text(encoding="utf-8")
REMOTE = Path("ops/aws/deploy_cn_radar_remote.sh").read_text(encoding="utf-8")
WORKFLOW = Path(".github/workflows/deploy-cn-radar-worker.yml").read_text(encoding="utf-8")


def test_cn_radar_installer_is_isolated_and_read_only():
    assert 'REPO_REF="${REPO_REF:?REPO_REF exact worker commit SHA is required}"' in INSTALL
    assert "evaluate_cn_observation_payload" in INSTALL
    assert "stock-razor-cn-radar.service" in INSTALL
    assert "PrivateNetwork=true" in INSTALL
    assert "NoNewPrivileges=true" in INSTALL
    assert "ReadOnlyPaths=/run/stock-razor-cn-eastmoney" in INSTALL
    assert "STOCK_RAZOR_CN_OBSERVATION_PATH" in INSTALL
    assert "market_data.seed" not in INSTALL
    assert "OpenQuoteContext" not in INSTALL
    assert "urlopen" not in INSTALL
    assert "order" not in INSTALL.lower()


def test_cn_radar_runtime_precomputes_only_on_source_sequence_change():
    assert "last_key = None" in INSTALL
    assert "last_evaluation = None" in INSTALL
    assert 'poll_status = "UNCHANGED"' in INSTALL
    assert "evaluate_cn_observation_payload(source)" in INSTALL
    assert '"research_only": True' in INSTALL
    assert '"can_confirm_signal": False' in INSTALL
    assert '"radar_admission": "BLOCKED"' in INSTALL
    assert '"live_trade": False' in INSTALL


def test_cn_radar_verifier_requires_qualified_bar_end_and_governed_currentness():
    assert 'evaluation.get("status") == "PASS"' in VERIFY
    assert 'item.get("signal_permission") == "record_only"' in VERIFY
    assert 'evaluation.get("intraday_timestamp_semantics_proven") is True' in VERIFY
    assert 'item.get("intraday_timestamp_semantics_proven") is (not is_tickflow)' in VERIFY
    assert '"cn_intraday_timestamp_semantics_unproven" not in risk_flags' in VERIFY
    assert 'isinstance(evaluation.get("intraday_currentness_proven"), bool)' in VERIFY
    assert 'if item.get("intraday_currentness_proven") is True:' in VERIFY
    assert '"cn_intraday_currentness_unproven" not in risk_flags' in VERIFY
    assert '"cn_intraday_currentness_unproven" in risk_flags' in VERIFY
    assert 'set(frames) == {"1d", "60m", "15m"}' in VERIFY
    assert 'systemctl show "$service" -p PrivateNetwork' in VERIFY


def test_cn_radar_workflow_uses_exact_main_and_ssm():
    assert "Deploy Read-Only CN Radar Worker" in WORKFLOW
    assert "actions/checkout@v4" in WORKFLOW
    assert "aws-actions/configure-aws-credentials@v4" in WORKFLOW
    assert "deploy_cn_radar_remote.sh" in WORKFLOW
    assert "DEPLOY_SHA" in WORKFLOW
    assert "install_cn_radar_worker.sh" in REMOTE
    assert "verify_cn_radar_worker.sh" in REMOTE
    assert "CN_RADAR_WORKER_AWS_DEPLOYMENT=PASS" in WORKFLOW
    assert "CN_RADAR_SSM_PREFLIGHT=PASS" in WORKFLOW
    assert "AWS-RunShellScript" in WORKFLOW


def test_cn_radar_worker_emits_truthful_runtime_latency_telemetry():
    assert "analysis_started = time.perf_counter()" in INSTALL
    assert '"radar_analysis_performed": radar_analysis_performed' in INSTALL
    assert '"radar_analysis_latency_ms": radar_analysis_latency_ms' in INSTALL
    assert '"data_to_radar_latency_ms": data_to_radar_latency_ms' in INSTALL
    assert 'poll_status = "UNCHANGED"' in INSTALL
    assert "radar_analysis_performed = False" in INSTALL
    assert '"emitted_at_utc": completed_at.isoformat()' in INSTALL


def test_cn_radar_verifier_requires_runtime_latency_telemetry_consistency():
    assert 'radar_analysis_performed = payload.get("radar_analysis_performed")' in VERIFY
    assert 'radar_analysis_latency_ms = payload.get("radar_analysis_latency_ms")' in VERIFY
    assert 'data_to_radar_latency_ms = payload.get("data_to_radar_latency_ms")' in VERIFY
    assert 'assert isinstance(radar_analysis_performed, bool)' in VERIFY
    assert 'assert payload.get("poll_status") == "PASS"' in VERIFY
    assert 'assert radar_analysis_latency_ms is None' in VERIFY
    assert 'assert data_to_radar_latency_ms is None' in VERIFY


def test_cn_radar_worker_does_not_clamp_future_source_to_fake_zero_latency():
    assert "source_delta_ms >= 0" in INSTALL
    assert "data_to_radar_latency_ms = round(source_delta_ms, 3)" in INSTALL
    assert "source_age_seconds = (" in INSTALL


def test_cn_radar_workflow_reports_only_whitelisted_ssm_failure_evidence():
    assert "StandardErrorContent" in WORKFLOW
    assert "ResponseCode" in WORKFLOW
    assert "CN_RADAR_SSM_STATUS=%s" in WORKFLOW
    assert "CN_RADAR_SSM_RESPONSE_CODE=%s" in WORKFLOW
    assert "CN_RADAR_FAILURE_CLASS=%s" in WORKFLOW
    assert "failure_class=INSTALL" in WORKFLOW
    assert "failure_class=ACCEPTANCE" in WORKFLOW
    assert "echo \"$stderr\"" not in WORKFLOW
    assert "StandardOutputContent or StandardErrorContent" not in WORKFLOW


def test_cn_radar_remote_command_reports_only_fixed_preflight_stages():
    for stage in ("INSTALL_DOWNLOAD", "INSTALL_HASH", "VERIFY_DOWNLOAD", "VERIFY_HASH", "VERIFY_OUTPUT"):
        assert f"CN_RADAR_STAGE={stage}" in REMOTE
    assert "for candidate in REMOTE_STARTED REMOTE_INIT TEMP_DIR DEPLOY_HELPER_DOWNLOAD DEPLOY_HELPER_HASH DEPLOY_HELPER_RUN INSTALL_DOWNLOAD INSTALL_HASH VERIFY_DOWNLOAD VERIFY_HASH INSTALL ACCEPTANCE VERIFY_OUTPUT" in WORKFLOW
    assert "printf '%s\\n' \"$stderr\"" not in WORKFLOW


def test_cn_radar_remote_temp_directory_failure_has_fixed_stage_code():
    assert 'if ! stage_dir="$(mktemp -d)"; then' in REMOTE
    assert "CN_RADAR_STAGE=TEMP_DIR" in REMOTE
    assert "CN_RADAR_REMOTE_EXIT_CODE=%s" in REMOTE
    assert "stage=REMOTE_INIT" in REMOTE
    assert "for candidate in REMOTE_STARTED REMOTE_INIT TEMP_DIR DEPLOY_HELPER_DOWNLOAD" in WORKFLOW
    assert "stage=REMOTE_SETUP" not in REMOTE


def test_cn_radar_failure_readback_retries_both_bounded_ssm_streams():
    assert "StandardErrorContent" in WORKFLOW
    assert "StandardOutputContent" in WORKFLOW
    assert "for _ in $(seq 1 5)" in WORKFLOW
    assert "sleep 2" in WORKFLOW
    assert 'evidence="${stderr} ${stdout}"' in WORKFLOW


def test_cn_radar_failure_classes_are_fixed_and_report_only_lengths():
    for category in ("REMOTE_NO_OUTPUT", "REMOTE_SYNTAX", "REMOTE_MISSING_COMMAND", "REMOTE_PERMISSION", "REMOTE_UNCLASSIFIED_OUTPUT"):
        assert category in WORKFLOW
    assert "CN_RADAR_SSM_STDOUT_CHARS=%s" in WORKFLOW
    assert "CN_RADAR_SSM_STDERR_CHARS=%s" in WORKFLOW
    assert '<<< "$evidence"' in WORKFLOW


def test_cn_radar_ssm_preflight_is_fixed_and_precedes_deployment_payload():
    assert "CN_RADAR_SSM_PROBE=PASS" in WORKFLOW
    assert WORKFLOW.index("CN_RADAR_SSM_PREFLIGHT=PASS") < WORKFLOW.index("The two immutable commit-path downloads")
    assert "CN_RADAR_SSM_PREFLIGHT=NOT_VERIFIED" in WORKFLOW


def test_cn_radar_ssm_probe_failure_reports_only_allowlisted_metadata():
    assert "CN_RADAR_SSM_PREFLIGHT_DETAILS=%s" in WORKFLOW
    assert "CN_RADAR_SSM_PREFLIGHT_RESPONSE_CODE=%s" in WORKFLOW
    assert "CN_RADAR_SSM_PREFLIGHT_STDOUT_CHARS=%s" in WORKFLOW
    assert "CN_RADAR_SSM_PREFLIGHT_STDERR_CHARS=%s" in WORKFLOW
    assert "probe_stderr" in WORKFLOW
    assert "StatusDetails" in WORKFLOW

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "ops/aws/install_us_radar_worker.sh").read_text()
VERIFY = (ROOT / "ops/aws/verify_us_radar_worker.sh").read_text()
WORKFLOW = (ROOT / ".github/workflows/deploy-us-radar-worker.yml").read_text()


def test_worker_installer_uses_isolated_minimal_analysis_environment():
    assert "/opt/stock-razor-us-radar" in INSTALLER
    assert "'numpy==1.26.4'" in INSTALLER
    assert "'pandas==2.2.2'" in INSTALLER
    assert "'PyYAML==6.0.2'" in INSTALLER
    assert "futu-api" not in INSTALLER
    assert "alpaca" not in INSTALLER.lower()
    assert "yfinance" not in INSTALLER.lower()
    assert "litellm" not in INSTALLER.lower()
    assert "openai" not in INSTALLER.lower()


def test_worker_runtime_is_network_isolated_and_fail_closed():
    assert "PrivateNetwork=true" in INSTALLER
    assert "NoNewPrivileges=true" in INSTALLER
    assert "ReadOnlyPaths=/run/stock-razor-us-livefeed" in INSTALLER
    assert '"research_only": True' in INSTALLER
    assert '"can_confirm_signal": False' in INSTALLER
    assert '"radar_admission": "BLOCKED"' in INSTALLER
    assert '"live_trade": False' in INSTALLER
    assert "last_research_state" not in INSTALLER
    assert "StockRadarProviderRuntime" not in INSTALLER
    assert ".seed(" not in INSTALLER
    assert ".subscribe(" not in INSTALLER


def test_worker_binds_worker_and_source_provenance_separately():
    assert 'REPO_REF="${REPO_REF:?REPO_REF exact worker commit SHA is required}"' in INSTALLER
    assert 'SOURCE_REPO_SHA="${SOURCE_REPO_SHA:?SOURCE_REPO_SHA exact acquisition commit SHA is required}"' in INSTALLER
    assert "STOCK_RAZOR_WORKER_REPO_SHA=$REPO_REF" in INSTALLER
    assert "STOCK_RAZOR_SOURCE_REPO_SHA=$SOURCE_REPO_SHA" in INSTALLER
    assert "expected_repo_sha=expected_source_repo_sha" in INSTALLER


def test_verify_requires_systemd_sandbox_and_research_only_contract():
    assert 'PrivateNetwork --value)" = "yes"' in VERIFY
    assert 'NoNewPrivileges --value)" = "yes"' in VERIFY
    assert 'payload.get("research_only") is True' in VERIFY
    assert 'payload.get("can_confirm_signal") is False' in VERIFY
    assert 'payload.get("radar_admission") == "BLOCKED"' in VERIFY
    assert 'payload.get("live_trade") is False' in VERIFY
    assert 'evaluation.get("source_delivery_mode") in {"UNKNOWN", "REALTIME"}' in VERIFY
    assert 'evaluation.get("source_bar_closure") in {"UNPROVEN", "PROVEN"}' in VERIFY
    assert 'evaluation.get("source_radar_admission") == "BLOCKED"' in VERIFY
    assert 'evaluation.get("source_live_trade") is False' in VERIFY
    assert 'diagnostics.get("decision") == "BLOCKED"' in VERIFY
    assert 'diagnostics.get("promotion_authorized") is False' in VERIFY
    assert 'diagnostics.get("source_radar_admission") == "BLOCKED"' in VERIFY
    assert 'diagnostics.get("source_live_trade") is False' in VERIFY
    assert 'diagnostics.get("delivery_mode_realtime") is (' in VERIFY
    assert 'diagnostics.get("bar_closure_proven") is (' in VERIFY
    assert 'diagnostics.get("minimum_source_prerequisites_met") is (' in VERIFY
    assert '"PROMOTION_NOT_AUTHORIZED" in diagnostic_reasons' in VERIFY
    assert "US_RADAR_WORKER_VERIFY=PASS" in VERIFY


def test_verify_only_allows_typed_fail_closed_block_reasons():
    assert "SOURCE_EXPORT_STALE" in VERIFY
    assert "SOURCE_EXPORT_FROM_FUTURE" in VERIFY
    assert "SOURCE_SEQUENCE_REGRESSION" in VERIFY
    assert "SOURCE_INVALID" not in VERIFY
    assert "SOURCE_REPO_SHA_MISMATCH" not in VERIFY


def test_workflow_discovers_livefeed_source_sha_before_deploy():
    assert "Discover canonical source SHA" in WORKFLOW
    assert "/run/stock-razor-us-livefeed/latest-heartbeat.json" in WORKFLOW
    assert "INVALID_SOURCE_REPO_SHA" in WORKFLOW
    assert "SOURCE_REPO_SHA" in WORKFLOW
    assert "steps.canonical.outputs.sha" in WORKFLOW
    assert "US_RADAR_WORKER_AWS_DEPLOYMENT=PASS" in WORKFLOW


def test_workflow_yaml_parses():
    parsed = yaml.safe_load(WORKFLOW)
    assert parsed["name"] == "Deploy Read-Only US Radar Worker"


def _embedded_source(text: str, marker: str, end_marker: str) -> str:
    start = text.index(marker)
    start = text.index("\n", start) + 1
    end = text.index(end_marker, start)
    return text[start:end]


def test_installer_embedded_worker_python_compiles():
    marker = "cat >\"$INSTALL_ROOT/run.py\" <<'PY'"
    source = _embedded_source(INSTALLER, marker, "\nPY\n\ncat >/etc/systemd")
    compile(source, "install_us_radar_worker.sh:run.py", "exec")


def test_installer_import_smoke_python_compiles():
    marker = 'PYTHONPATH="$INSTALL_ROOT/repo" "$INSTALL_ROOT/venv/bin/python" - <<\'PY\''
    source = _embedded_source(INSTALLER, marker, "\nPY\n\ncat >\"$INSTALL_ROOT/run.py\"")
    compile(source, "install_us_radar_worker.sh:import-smoke", "exec")


def test_verify_embedded_python_compiles():
    marker = '"$python_bin" - "$status" "$expected_worker_sha" "$expected_source_sha" <<\'PY\''
    source = _embedded_source(VERIFY, marker, "\nPY\n")
    compile(source, "verify_us_radar_worker.sh:verify", "exec")

def test_worker_never_republishes_last_good_state_when_current_evaluation_blocks():
    assert "last_research_state" not in INSTALLER


def test_source_sha_discovery_ignores_trailing_blank_lines_and_emits_invocation():
    discover = WORKFLOW.split("      - name: Discover canonical source SHA", 1)[1].split(
        "      - name: Deploy exact worker SHA over SSM", 1
    )[0]
    assert "printf '%s\\n' \"$inv\"" in discover
    assert "awk '/^[0-9a-f]{40}$/ {sha=$0} END {print sha}'" in discover
    assert "tail -n 1" not in discover
    assert 'echo "INVALID_SOURCE_REPO_SHA" >&2' in discover


def test_source_sha_discovery_retries_during_livefeed_restart_window():
    discover = WORKFLOW.split("      - name: Discover canonical source SHA", 1)[1].split(
        "      - name: Deploy exact worker SHA over SSM", 1
    )[0]
    assert "for _ in $(seq 1 30); do" in discover
    assert "if [ -s /run/stock-razor-us-livefeed/latest-heartbeat.json ]; then" in discover
    assert "sleep 2" in discover
    assert "CANONICAL_SOURCE_HEARTBEAT_TIMEOUT" in discover
    assert "&& exit 0" in discover


def test_worker_consumes_daily_history_without_provider_access():
    assert "load_futu_us_daily_history_frames" in INSTALLER
    assert '"/run/stock-razor-us-livefeed/daily-history.json"' in INSTALLER
    assert "daily_frames=daily_frames" in INSTALLER
    assert '"daily_history": daily_history' in INSTALLER
    assert "PrivateNetwork=true" in INSTALLER
    assert "futu-api" not in INSTALLER


def test_worker_verifier_requires_daily_context_in_actual_technical_state():
    assert 'daily_history.get("status") == "PASS"' in VERIFY
    assert 'daily_history.get("historical_query") is True' in VERIFY
    assert 'daily_history.get("currentness_proven") is False' in VERIFY
    assert 'daily_history.get("bar_closure_promotion_authorized") is False' in VERIFY
    assert 'int(item.get("row_count") or 0) >= 120' in VERIFY
    assert 'quality.get("status") != "missing"' in VERIFY
    assert 'int(quality.get("bars") or 0) >= 60' in VERIFY
    assert '"1d_data_missing" not in set(quality.get("warnings") or [])' in VERIFY
    assert 'technical_state.get("research_only") is True' in VERIFY
    assert 'technical_state.get("can_confirm_signal") is False' in VERIFY


def test_embedded_worker_runtime_imports_daily_history_reader():
    marker = "cat >\"$INSTALL_ROOT/run.py\" <<'PY'"
    source = _embedded_source(INSTALLER, marker, "\nPY\n\ncat >/etc/systemd")
    assert "from src.services.stock_radar_v2.daily_history_reader import (" in source
    assert "load_futu_us_daily_history_frames" in source
    assert source.index("load_futu_us_daily_history_frames") < source.index(
        "daily_frames, daily_history = load_futu_us_daily_history_frames("
    )


def test_options_context_slot_is_opt_in_and_requires_exact_source_provenance():
    assert 'OPTIONS_CONTEXT_ENABLED="${OPTIONS_CONTEXT_ENABLED:-false}"' in INSTALLER
    assert 'OPTIONS_SOURCE_REPO_SHA="${OPTIONS_SOURCE_REPO_SHA:-}"' in INSTALLER
    assert 'if [ "$OPTIONS_CONTEXT_ENABLED" = "true" ]; then' in INSTALLER
    assert "OPTIONS_SOURCE_REPO_SHA exact options source SHA is required when enabled" in INSTALLER
    assert 'test "${#OPTIONS_SOURCE_REPO_SHA}" -eq 40' in INSTALLER
    assert "STOCK_RAZOR_OPTIONS_CONTEXT_ENABLED=$OPTIONS_CONTEXT_ENABLED" in INSTALLER
    assert "STOCK_RAZOR_OPTIONS_SOURCE_REPO_SHA=$OPTIONS_SOURCE_REPO_SHA" in INSTALLER


def test_options_context_keeps_radar_network_isolated_and_context_only():
    assert "from src.services.stock_radar_v2.options_context_reader import RadarOptionsContextReader" in INSTALLER
    assert "options_result = options_reader.read_file(" in INSTALLER
    assert "options_contexts = options_result.by_symbol()" in INSTALLER
    assert "options_contexts=options_contexts" in INSTALLER
    assert '"options_context": {' in INSTALLER
    assert "ReadOnlyPaths=-/run/stock-razor-us-options-intelligence" in INSTALLER
    assert "PrivateNetwork=true" in INSTALLER
    assert "futu-api" not in INSTALLER
    assert "alpaca" not in INSTALLER.lower()


def test_us_radar_worker_emits_truthful_runtime_latency_telemetry():
    assert "analysis_started = time.perf_counter()" in INSTALLER
    assert 'radar_analysis_performed = evaluation.status == "PASS"' in INSTALLER
    assert '"radar_analysis_performed": radar_analysis_performed' in INSTALLER
    assert '"radar_analysis_latency_ms": radar_analysis_latency_ms' in INSTALLER
    assert '"data_to_radar_latency_ms": data_to_radar_latency_ms' in INSTALLER
    assert '"emitted_at_utc": completed_at.isoformat()' in INSTALLER

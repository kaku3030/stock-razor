from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INSTALLER=(ROOT/"ops/aws/install_us_opend_livefeed.sh").read_text()
WORKFLOW=(ROOT/".github/workflows/deploy-us-opend-livefeed.yml").read_text()
VERIFY=(ROOT/"ops/aws/verify_us_opend_livefeed.sh").read_text()

def test_installer_is_read_only_and_fail_closed():
    assert "stock-razor-us-livefeed.service" in INSTALLER
    assert "FutuK1MStreamingAdapter" in INSTALLER
    assert "LiveFeedRuntimeBridge" in INSTALLER
    assert '"delivery_mode":delivery_mode_state' in INSTALLER
    assert '"quote_right_evidence":quote_right_payload' in INSTALLER
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
    assert '"delivery_mode":"(UNKNOWN|REALTIME)"' in WORKFLOW
    assert '"quote_right_evidence":' in WORKFLOW
    assert '"bar_closure":"(UNPROVEN|PROVEN)"' in WORKFLOW
    assert '"radar_admission":"BLOCKED"' in WORKFLOW
    assert '"closure_pipeline":' in WORKFLOW
    assert '"k1m_closure_qualification":' in WORKFLOW
    assert '"k1m_closure_qualification_summary":' in WORKFLOW
    assert '"can_promote":false' in WORKFLOW
    assert '"research_consumer":' in WORKFLOW
    assert '"canonical_cache":' in WORKFLOW
    assert '"canonical_snapshot_export":{"status":"PASS"' in WORKFLOW
    assert "CANONICAL_SNAPSHOT_EXPORT=PASS" in WORKFLOW
    assert "canonical-market-snapshot.json" in WORKFLOW
    assert "US_OPEND_LIVEFEED_AWS_DEPLOYMENT=PASS" in WORKFLOW


def test_status_audit_is_read_only_and_covers_us_livefeed_runtime():
    ops = (ROOT/".github/workflows/aws-ssm-ops.yml").read_text()
    assert "- us_livefeed_status" in ops
    assert "stock-razor-us-livefeed.service" in ops
    assert "11111" in ops
    assert "/run/stock-razor-us-livefeed/latest-heartbeat.json" in ops
    assert "/run/stock-razor-us-livefeed/canonical-market-snapshot.json" in ops
    assert "=== CANONICAL SNAPSHOT EXPORT ===" in ops
    assert '"latest_end_utc":' in ops
    assert '"radar_admission":payload.get("radar_admission")' in ops
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
    assert '"event_count":data_count' in installer
    assert '"accepted_event_count":accepted_count' in installer
    assert "Restart=on-failure" in installer


def test_installer_publishes_session_aware_k1m_currentness_with_fail_closed_closure_promotion():
    installer=(ROOT/"ops/aws/install_us_opend_livefeed.sh").read_text()
    assert "classify_futu_us_k1m_currentness" in installer
    assert "summarize_futu_k1m_currentness" in installer
    assert "ctx.get_global_state()" in installer
    assert 'state_data.get("market_us")' in installer
    assert '"market_state_us":market_state' in installer
    assert '"market_state_evidence":"PASS" if state_ret==ft.RET_OK else "BLOCKED"' in installer
    assert '"latest_k1m_time_keys":time_keys' in installer
    assert '"k1m_currentness":currentness_payload' in installer
    assert '"interval_start_utc":(' in installer
    assert '"interval_end_utc":(' in installer
    assert '"end_offset_seconds":result.end_offset_seconds' in installer
    assert '"k1m_currentness_summary":currentness_summary' in installer
    assert "derive_futu_k1m_bar_closure_state" in installer
    assert "bar_closure_evidence_state=derive_futu_k1m_bar_closure_state" in installer
    assert '"delivery_mode":delivery_mode_state' in installer
    assert '"bar_closure":bar_closure_state' in installer
    assert '"radar_admission":"BLOCKED"' in installer
    assert '"live_trade":False' in installer


def test_installer_enables_only_explicit_sync_transport_lifecycle_evidence():
    installer=(ROOT/"ops/aws/install_us_opend_livefeed.sh").read_text()
    assert 'OpenQuoteContext(host="127.0.0.1",port=11111)' in installer
    assert "OPEND_SYNC_CONTEXT_CONNECTED_EVIDENCE" in installer
    assert "futu-api 10.11.7108" in installer
    assert "_init_connect_sync() reports RET_OK" in installer
    assert '"delivery_mode":delivery_mode_state' in installer
    assert '"radar_admission":"BLOCKED"' in installer
    assert '"live_trade":False' in installer

def test_deploy_gate_waits_for_bounded_self_heal_and_exact_sha():
    workflow=(ROOT/".github/workflows/deploy-us-opend-livefeed.yml").read_text()
    assert "verify_us_opend_livefeed.sh" in workflow
    assert "REPO_REF=$REPO_REF" in workflow
    assert "event_count" in workflow
    assert "sleep 5" in workflow



def _embedded_runtime_python() -> str:
    marker = 'cat >"$INSTALL_ROOT/run.py" <<\'PY\'\n'
    start = INSTALLER.index(marker) + len(marker)
    end = INSTALLER.index("\nPY\n\ncat >/etc/systemd/system", start)
    return INSTALLER[start:end]


def test_installer_embedded_runtime_python_compiles():
    compile(_embedded_runtime_python(), "install_us_opend_livefeed.sh:run.py", "exec")


def test_installer_wires_writer_qualified_closure_into_ingest_only_cache():
    installer = INSTALLER
    assert "FutuK1MClosurePipeline" in installer
    assert "FutuK1MResearchConsumer" in installer
    assert "RealtimeMarketDataService" in installer
    assert "futu_us_market_state_to_session" in installer
    assert "consumer_result=research_consumer.run_once(max_events=1000)" in installer
    assert installer.index("snap=bridge.drain()") < installer.index(
        "consumer_result=research_consumer.run_once(max_events=1000)"
    )
    assert '"closure_pipeline":closure_diagnostics' in installer
    assert '"research_consumer":consumer_payload' in installer
    assert '"canonical_cache":canonical_cache' in installer
    assert '"cache_session_us":cache_session' in installer
    assert '"bar_count_5m":len(bars_5m)' in installer
    assert '"bar_count_15m":len(bars_15m)' in installer
    assert '"bar_count_1h":len(bars_1h)' in installer
    assert '"latest_5m_end_utc":' in installer
    assert '"latest_15m_end_utc":' in installer
    assert '"latest_1h_end_utc":' in installer
    assert "build_canonical_snapshot_export" in installer
    assert "write_canonical_snapshot_export(canonical_snapshot_path,canonical_export)" in installer
    assert "canonical_export_status=\"PASS\"" in installer
    assert "canonical_export_status=\"BLOCKED\"" in installer
    assert "canonical_export_error=type(exc).__name__" in installer
    assert "consumer_result.bars_ingested > 0" in installer
    assert "not os.path.exists(canonical_snapshot_path)" in installer
    assert "market_state != last_export_market_state" in installer
    assert 'canonical_export_status != "PASS"' in installer
    assert "canonical_export_sequence=next_export_sequence" in installer
    assert '"updated":canonical_export_updated' in installer
    assert '"last_write_utc":canonical_export_last_write_utc' in installer
    assert '"canonical_snapshot_export":{' in installer
    assert '"status":canonical_export_status' in installer
    assert "STOCK_RAZOR_CANONICAL_SNAPSHOT_PATH" in installer
    assert '"controller_findings_tail":list(snap.controller.findings[-20:])' in installer


def test_installer_canonical_cache_fallback_health_and_admission_remain_fail_closed():
    installer = INSTALLER
    assert "freshness=0.0,completeness=0.0,timestamp=0.0" in installer
    assert 'quality_flags=("MISSING_BAR","TIMESTAMP_SEMANTICS_UNVERIFIED")' in installer
    assert '"delivery_mode":delivery_mode_state' in installer
    assert '"bar_closure":bar_closure_state' in installer
    assert '"radar_admission":"BLOCKED"' in installer
    assert '"live_trade":False' in installer


def test_verify_gate_requires_atomic_canonical_snapshot_with_exact_provenance():
    assert "canonical-market-snapshot.json" in VERIFY
    assert 'snapshot.get("schema") == "stock_razor_canonical_market_snapshot_v1"' in VERIFY
    assert 'snapshot.get("repo_sha") == expected_sha' in VERIFY
    assert 'snapshot.get("runtime_instance_id") == heartbeat.get("runtime_instance_id")' in VERIFY
    assert 'snapshot_sequence == int(export.get("sequence") or -2)' in VERIFY
    assert "snapshot_sequence > 0" in VERIFY
    assert 'export.get("last_write_utc")' in VERIFY
    assert 'export.get("status") == "PASS"' in VERIFY
    assert 'heartbeat.get("delivery_mode") == expected_delivery_mode' in VERIFY
    assert 'snapshot.get("delivery_mode") == expected_delivery_mode' in VERIFY
    assert 'export.get("delivery_mode") == expected_delivery_mode' in VERIFY
    assert 'snapshot.get("bar_closure") == expected_bar_closure' in VERIFY
    assert 'export.get("bar_closure") == expected_bar_closure' in VERIFY
    assert 'snapshot.get("radar_admission") == "BLOCKED"' in VERIFY
    assert 'snapshot.get("live_trade") is False' in VERIFY
    assert "CANONICAL_SNAPSHOT_EXPORT=PASS" in VERIFY


def test_status_snapshot_summary_embedded_python_compiles():
    ops = (ROOT/".github/workflows/aws-ssm-ops.yml").read_text()
    marker = '/opt/stock-razor-opend-client/venv/bin/python - "$snapshot_path" <<\'PY\''
    start = ops.index(marker)
    start = ops.index("\n", start) + 1
    end = ops.index("\n          PY", start)
    source = "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in ops[start:end].splitlines()
    )
    compile(source, "aws-ssm-ops.yml:canonical-snapshot-summary", "exec")


def test_verify_snapshot_provenance_embedded_python_compiles():
    marker = '"$python_bin" - "$status" "$snapshot" "$expected_sha" <<\'PY\''
    start = VERIFY.index(marker)
    start = VERIFY.index("\n", start) + 1
    end = VERIFY.index("\nPY", start)
    compile(VERIFY[start:end], "verify_us_opend_livefeed.sh:snapshot-provenance", "exec")


def test_verify_gate_prints_pass_marker_on_its_own_line():
    cat_index = VERIFY.index('cat "$status"')
    newline_index = VERIFY.index("printf '\\n'", cat_index)
    pass_index = VERIFY.index('echo "CANONICAL_SNAPSHOT_EXPORT=PASS"', newline_index)
    assert cat_index < newline_index < pass_index



def test_installer_tracks_closure_qualification_and_promotes_only_aggregate_state():
    installer = INSTALLER
    assert "FutuK1MClosureQualificationTracker" in installer
    assert "summarize_futu_k1m_closure_qualification" in installer
    assert "derive_futu_k1m_bar_closure_state" in installer
    assert "required_consecutive_boundaries=3" in installer
    assert '"k1m_closure_qualification":closure_qualification_payload' in installer
    assert '"k1m_closure_qualification_summary":closure_qualification_summary' in installer
    assert '"can_promote":result.can_promote' in installer
    assert "bar_closure_evidence_state=derive_futu_k1m_bar_closure_state" in installer
    assert "bar_closure_evidence_state != last_export_bar_closure" in installer
    assert "bar_closure=bar_closure_evidence_state" in installer
    assert 'last_export_bar_closure=bar_closure_evidence_state' in installer
    assert '"bar_closure_evidence_state":bar_closure_evidence_state' in installer
    assert '"bar_closure":bar_closure_state' in installer
    assert '"delivery_mode":delivery_mode_state' in installer
    assert '"radar_admission":"BLOCKED"' in installer
    assert '"live_trade":False' in installer


def test_verify_gate_derives_dynamic_bar_closure_but_preserves_other_gates():
    assert 'heartbeat.get("k1m_closure_qualification")' in VERIFY
    assert 'heartbeat.get("k1m_closure_qualification_summary")' in VERIFY
    assert 'heartbeat.get("k1m_currentness_summary")' in VERIFY
    assert 'item.get("can_promote") is False' in VERIFY
    assert '"PROVEN"' in VERIFY
    assert 'currentness_summary == "PASS" and closure_summary == "PASS"' in VERIFY
    assert 'heartbeat.get("bar_closure_evidence_state") == expected_bar_closure' in VERIFY
    assert 'heartbeat.get("bar_closure") == expected_bar_closure' in VERIFY
    assert 'snapshot.get("bar_closure") == expected_bar_closure' in VERIFY
    assert 'export.get("bar_closure") == expected_bar_closure' in VERIFY
    assert 'snapshot.get("radar_admission") == "BLOCKED"' in VERIFY
    assert 'snapshot.get("live_trade") is False' in VERIFY


def test_installer_refreshes_quote_right_and_promotes_delivery_non_sticky():
    installer = INSTALLER
    assert "classify_futu_us_quote_right" in installer
    assert "quote_right_poll_seconds=60.0" in installer
    assert "quote_right_max_age_seconds=90.0" in installer
    assert "ctx.get_user_info([ft.UserInfoField.QOTRIGHT])" in installer
    assert 'quote_right_query_status="PASS"' in installer
    assert 'quote_right_query_status="BLOCKED"' in installer
    assert 'quote_right_raw="UNKNOWN"' in installer
    assert "delivery_mode_evidence_state=quote_right_classification.delivery_mode" in installer
    assert "delivery_mode_evidence_state != last_export_delivery_mode" in installer
    assert "delivery_mode=delivery_mode_evidence_state" in installer
    assert "last_export_delivery_mode=delivery_mode_evidence_state" in installer
    assert '"quote_right_evidence":quote_right_payload' in installer
    assert '"delivery_mode":last_export_delivery_mode or "UNKNOWN"' in installer
    assert '"delivery_mode":delivery_mode_state' in installer
    assert '"radar_admission":"BLOCKED"' in installer
    assert '"live_trade":False' in installer


def test_verify_gate_derives_delivery_from_fresh_quote_right_evidence():
    assert 'quote_right = heartbeat.get("quote_right_evidence") or {}' in VERIFY
    assert 'quote_right.get("query_status") == "PASS"' in VERIFY
    assert '"LV3"' in VERIFY
    assert 'age <= max_age' in VERIFY
    assert 'expected_delivery_mode = "REALTIME" if fresh_realtime else "UNKNOWN"' in VERIFY
    assert 'heartbeat.get("delivery_mode") == expected_delivery_mode' in VERIFY
    assert 'snapshot.get("delivery_mode") == expected_delivery_mode' in VERIFY
    assert 'export.get("delivery_mode") == expected_delivery_mode' in VERIFY
    assert 'snapshot.get("radar_admission") == "BLOCKED"' in VERIFY
    assert 'snapshot.get("live_trade") is False' in VERIFY


def test_installer_warm_starts_from_same_opend_context_without_promoting_live_evidence():
    installer = INSTALLER
    assert "build_futu_k1m_warm_start_plan" in installer
    assert 'ctx.request_history_kline(' in installer
    assert installer.count('OpenQuoteContext(host="127.0.0.1",port=11111)') == 1
    assert "ktype=ft.KLType.K_1M" in installer
    assert "autype=ft.AuType.NONE" in installer
    assert "max_count=1000" in installer
    assert "page_req_key=page_req_key" in installer
    assert "extended_time=False" in installer
    assert "warm_start_lookback_days=10" in installer
    assert "warm_start_max_pages=4" in installer
    assert '"reason":"HISTORY_QUERY_PAGE_LIMIT_REACHED"' in installer
    assert "market_data.ingest(bar)" in installer
    assert "market_data.seed(" not in installer
    assert installer.index("for code in CODES:") < installer.index("bridge.start(streams)")
    assert '"historical_warm_start":{' in installer
    assert '"realtime_currentness_proven":False' in installer
    assert '"bar_closure_promotion_authorized":False' in installer
    assert '"radar_admission":"BLOCKED"' in installer
    assert '"live_trade":False' in installer


def test_installer_warm_start_failure_is_observable_but_does_not_abort_live_start():
    installer = INSTALLER
    warm_exception = installer.index('"reason":"WARM_START_EXCEPTION:"+type(exc).__name__')
    bridge_start = installer.index("bridge.start(streams)")
    assert warm_exception < bridge_start
    assert 'warm_start_status=(' in installer
    assert '"status":warm_start_status' in installer
    assert '"total_bars_ingested":warm_start_total_seeded' in installer
    assert "raise RuntimeError" not in installer[warm_exception:bridge_start]

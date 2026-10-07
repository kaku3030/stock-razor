from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "ops/aws/install_us_options_intelligence.sh").read_text()


def _embedded_source(text: str, marker: str, end_marker: str) -> str:
    start = text.index(marker)
    start = text.index("\n", start) + 1
    end = text.index(end_marker, start)
    return text[start:end]


def test_installer_requires_exact_repo_sha_and_loopback_opend():
    assert 'REPO_REF="${REPO_REF:?REPO_REF exact collector commit SHA is required}"' in INSTALLER
    assert 'OPEND_HOST="${OPEND_HOST:-127.0.0.1}"' in INSTALLER
    assert 'echo "OPEND_HOST must remain 127.0.0.1"' in INSTALLER
    assert 'test "${#REPO_REF}" -eq 40' in INSTALLER
    assert "STOCK_RAZOR_OPTIONS_REPO_SHA=$REPO_REF" in INSTALLER


def test_installer_uses_isolated_pinned_runtime():
    assert "'numpy==1.26.4'" in INSTALLER
    assert "'pandas==2.2.2'" in INSTALLER
    assert "'exchange-calendars==4.13.2'" in INSTALLER
    assert "'futu-api==10.8.6808'" in INSTALLER
    assert "/opt/stock-razor-us-options-intelligence" in INSTALLER


def test_collector_has_no_trade_context_or_order_surface():
    assert "OpenTradeContext" not in INSTALLER
    assert "place_order" not in INSTALLER
    assert "modify_order" not in INSTALLER
    assert "cancel_order" not in INSTALLER
    assert '"trading_authority": False' in INSTALLER
    assert '"live_trade": False' in INSTALLER


def test_systemd_network_is_restricted_to_localhost():
    assert "PrivateNetwork=true" not in INSTALLER
    assert "IPAddressDeny=any" in INSTALLER
    assert "IPAddressAllow=localhost" in INSTALLER
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in INSTALLER
    assert "NoNewPrivileges=true" in INSTALLER
    assert "CapabilityBoundingSet=" in INSTALLER
    assert "ProtectSystem=strict" in INSTALLER
    assert "ProtectHome=true" in INSTALLER


def test_closed_sessions_do_not_open_provider_connection():
    source = _embedded_source(
        INSTALLER,
        'cat >"$INSTALL_ROOT/run.py" <<\'PY\'',
        "\nPY\n",
    )
    session_check = 'if session.status == "READY":'
    provider_open = "with source:"
    assert session_check in source
    assert provider_open in source
    assert source.index(session_check) < source.index(provider_open)


def test_embedded_runtime_compiles():
    source = _embedded_source(
        INSTALLER,
        'cat >"$INSTALL_ROOT/run.py" <<\'PY\'',
        "\nPY\n",
    )
    compile(source, "install_us_options_intelligence.sh:run.py", "exec")


def test_import_smoke_compiles():
    source = _embedded_source(
        INSTALLER,
        'PYTHONPATH="$INSTALL_ROOT/repo" "$INSTALL_ROOT/venv/bin/python" - <<\'PY\'',
        "\nPY\n",
    )
    compile(source, "install_us_options_intelligence.sh:import-smoke", "exec")


def test_default_scope_is_single_qqq_until_rate_and_freshness_are_qualified():
    assert 'SYMBOLS="${SYMBOLS:-US.QQQ}"' in INSTALLER
    assert 'POLL_SECONDS="${POLL_SECONDS:-60}"' in INSTALLER
    assert "snapshot_batch_size=200" in INSTALLER
    assert "chain_days=7" in INSTALLER


VERIFY = (ROOT / "ops/aws/verify_us_options_intelligence.sh").read_text()
WORKFLOW = (ROOT / ".github/workflows/deploy-us-options-intelligence.yml").read_text()


def test_verifier_requires_real_sidecar_by_default_deployment_path():
    assert 'require_snapshot="${REQUIRE_SNAPSHOT:-true}"' in VERIFY
    assert 'snapshot="/run/stock-razor-us-options-intelligence/options-intelligence.json"' in VERIFY
    assert 'assert snapshot_written is True' in VERIFY
    assert 'assert packet.get("radar_admission") == "CONTEXT_ONLY"' in VERIFY
    assert 'assert packet.get("decision_permission") == "BLOCKED_V0_1"' in VERIFY
    assert 'assert packet.get("trading_authority") is False' in VERIFY
    assert 'assert packet.get("live_trade") is False' in VERIFY
    assert "US_OPTIONS_INTELLIGENCE_VERIFY=PASS" in VERIFY
    assert "LIVE_TRADE=NO" in VERIFY


def test_verifier_embedded_python_compiles():
    marker = '"$python_bin" - "$status" "$snapshot" "$expected_sha" "$require_snapshot" <<\'PY\''
    source = _embedded_source(VERIFY, marker, "\nPY\n")
    compile(source, "verify_us_options_intelligence.sh:verify", "exec")


def test_workflow_is_manual_main_exact_sha_deployment():
    import yaml

    parsed = yaml.safe_load(WORKFLOW)
    assert parsed["name"] == "Deploy US Options Intelligence Collector"
    trigger = parsed.get("on", parsed.get(True))
    assert trigger == {"workflow_dispatch": None}
    assert "ref: main" in WORKFLOW
    assert 'echo "sha=$(git rev-parse HEAD)"' in WORKFLOW
    assert "REPO_REF: \"${{ steps.source.outputs.sha }}\"" in WORKFLOW
    assert "REQUIRE_SNAPSHOT=true" in WORKFLOW
    assert "US_OPTIONS_INTELLIGENCE_AWS_DEPLOYMENT=PASS" in WORKFLOW


def test_workflow_closes_windows_bash_syntax_evidence_gap_before_ssm():
    syntax_step = WORKFLOW.split("- id: source", 1)[1].split(
        "- uses: aws-actions/configure-aws-credentials@v4", 1
    )[0]
    assert "bash -n ops/aws/install_us_options_intelligence.sh" in syntax_step
    assert "bash -n ops/aws/verify_us_options_intelligence.sh" in syntax_step
    assert WORKFLOW.index("bash -n ops/aws/install_us_options_intelligence.sh") < WORKFLOW.index(
        "aws ssm send-command"
    )


def test_workflow_reasserts_context_only_and_no_live_trade():
    assert "US_OPTIONS_INTELLIGENCE_VERIFY=PASS" in WORKFLOW
    assert "RADAR_ADMISSION=CONTEXT_ONLY" in WORKFLOW
    assert "LIVE_TRADE=NO" in WORKFLOW
    assert '"trading_authority":false' in WORKFLOW
    assert '"live_trade":false' in WORKFLOW


def test_verifier_requires_runtime_loopback_only_enforcement_evidence():
    assert "IPAddressDeny=any" in VERIFY
    assert "IPAddressAllow=localhost" in VERIFY
    assert 'socket.create_connection(("127.0.0.1", 11111), timeout=2)' in VERIFY
    assert 'socket.create_connection(("1.1.1.1", 443), timeout=2)' in VERIFY
    assert "errno.EPERM" in VERIFY
    assert "errno.EACCES" in VERIFY
    assert "systemd-run --quiet --wait --pipe --collect" in VERIFY
    assert "NETWORK_SANDBOX_ENFORCEMENT=PASS" in VERIFY


def test_workflow_requires_network_sandbox_enforcement_before_deployment_pass():
    assert "NETWORK_SANDBOX_ENFORCEMENT=PASS" in WORKFLOW
    assert WORKFLOW.index("NETWORK_SANDBOX_ENFORCEMENT=PASS") < WORKFLOW.index(
        "US_OPTIONS_INTELLIGENCE_AWS_DEPLOYMENT=PASS"
    )

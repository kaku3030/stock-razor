from pathlib import Path


INSTALL = Path("ops/aws/install_cn_radar_worker.sh").read_text(encoding="utf-8")
VERIFY = Path("ops/aws/verify_cn_radar_worker.sh").read_text(encoding="utf-8")
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


def test_cn_radar_verifier_requires_research_state_and_precision_warnings():
    assert 'evaluation.get("status") == "PASS"' in VERIFY
    assert 'item.get("signal_permission") == "record_only"' in VERIFY
    assert '"cn_intraday_timestamp_semantics_unproven" in risk_flags' in VERIFY
    assert '"cn_intraday_currentness_unproven" in risk_flags' in VERIFY
    assert 'set(frames) == {"1d", "60m", "15m"}' in VERIFY
    assert 'systemctl show "$service" -p PrivateNetwork' in VERIFY


def test_cn_radar_workflow_uses_exact_main_and_ssm():
    assert "Deploy Read-Only CN Radar Worker" in WORKFLOW
    assert "actions/checkout@v4" in WORKFLOW
    assert "aws-actions/configure-aws-credentials@v4" in WORKFLOW
    assert "install_cn_radar_worker.sh" in WORKFLOW
    assert "verify_cn_radar_worker.sh" in WORKFLOW
    assert "CN_RADAR_WORKER_AWS_DEPLOYMENT=PASS" in WORKFLOW

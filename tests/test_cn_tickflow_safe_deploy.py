from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/deploy-cn-tickflow-research.yml").read_text(encoding="utf-8")
INSTALL = (ROOT / "ops/aws/install_cn_tickflow_research.sh").read_text(encoding="utf-8")
VERIFY = (ROOT / "ops/aws/verify_cn_tickflow_research.sh").read_text(encoding="utf-8")


def test_workflow_is_explicit_and_dry_run_by_default():
    assert "target_instance_id:" in WORKFLOW
    assert "options: [dry-run, deploy]" in WORKFLOW
    assert "default: dry-run" in WORKFLOW
    assert "DEPLOY_CN_TICKFLOW_WORKER" in WORKFLOW
    assert "github.actor == github.repository_owner" in WORKFLOW
    assert "github.ref == 'refs/heads/main'" in WORKFLOW
    assert "CN_TICKFLOW_SSM_TARGET_PREFLIGHT=PASS" in WORKFLOW
    assert "CN_TICKFLOW_DEPLOY_DRY_RUN=PASS" in WORKFLOW
    assert "CN_TICKFLOW_CANONICAL_WRITE=NO" in WORKFLOW
    assert "deploy-readonly-mcp" not in WORKFLOW


def test_workflow_checks_pre_and_post_identity_without_raw_ssm_logs():
    assert "CN_TICKFLOW_PRE_DEPLOY_READBACK=PASS" in WORKFLOW
    assert "CN_TICKFLOW_WORKER_REPO_SHA=$GITHUB_SHA" in WORKFLOW
    assert "CN_TICKFLOW_SOURCE_REPO_SHA=$GITHUB_SHA" in WORKFLOW
    assert "CN_TICKFLOW_PROVIDER=TICKFLOW_PREMIUM" in WORKFLOW
    assert "jq '{Status,ResponseCode}'" in WORKFLOW
    assert "sha256sum -c - >/dev/null" in WORKFLOW
    assert "MCP_DEPLOY" not in WORKFLOW


def test_workflow_classifies_ssm_target_failure_without_emitting_raw_metadata():
    assert "CN_TICKFLOW_SSM_RECORD=" in WORKFLOW
    assert "CN_TICKFLOW_SSM_ID_MATCH=" in WORKFLOW
    assert "CN_TICKFLOW_SSM_PING=" in WORKFLOW
    assert "CN_TICKFLOW_SSM_PLATFORM=" in WORKFLOW
    assert "CN_TICKFLOW_SSM_TARGET_DIAGNOSIS=" in WORKFLOW
    assert '"TARGET_NOT_REGISTERED"' in WORKFLOW
    assert '"SSM_NOT_ONLINE"' in WORKFLOW
    assert '"PLATFORM_NAME_MISMATCH"' in WORKFLOW
    assert 'elif (.PlatformName // "") | test("Amazon Linux")' in WORKFLOW
    assert 'echo "$info"' not in WORKFLOW


def test_installer_is_fail_closed_and_has_rollback():
    assert 'DEPLOY_DRY_RUN="${DEPLOY_DRY_RUN:-false}"' in INSTALL
    assert 'ALLOW_SERVICE_MUTATION="${ALLOW_SERVICE_MUTATION:-false}"' in INSTALL
    assert '[[ "$ALLOW_SERVICE_MUTATION" == "true" ]]' in INSTALL
    assert 'trap rollback ERR' in INSTALL
    assert 'CN_TICKFLOW_ROLLBACK=ATTEMPTED' in INSTALL
    assert 'CN_TICKFLOW_SERVICE_MUTATION=APPLIED' in INSTALL


def test_verifier_binds_worker_source_and_provider_and_keeps_gates_closed():
    assert 'payload.get("repo_sha") == expected' in VERIFY
    assert 'payload.get("provider") == "TICKFLOW_PREMIUM"' in VERIFY
    assert 'payload.get("source_arbiter_admission") == "BLOCKED"' in VERIFY
    assert 'payload.get("radar_admission") == "BLOCKED"' in VERIFY
    assert 'payload.get("live_trade") is False' in VERIFY
    assert 'CN_TICKFLOW_PROVIDER_QUALIFICATION=NOT_VERIFIED' in VERIFY


def test_verifier_requires_multiday_warmup_for_the_four_research_etfs():
    assert 'expected_symbols={"159611.SZ","159209.SZ","512730.SH","159363.SZ"}' in VERIFY
    assert '("15m",96),("60m",24),("1d",60)' in VERIFY
    assert '"CN_TICKFLOW_HISTORY_WARMUP=PASS"' in VERIFY
    assert '"ROW_COUNT_BELOW_MIN"' not in VERIFY  # short data cannot be accepted

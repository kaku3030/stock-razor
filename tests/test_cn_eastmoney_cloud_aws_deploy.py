from pathlib import Path


INSTALL = Path("ops/aws/install_cn_eastmoney_observer.sh").read_text(encoding="utf-8")
VERIFY = Path("ops/aws/verify_cn_eastmoney_observer.sh").read_text(encoding="utf-8")
WORKFLOW = Path(".github/workflows/deploy-cn-eastmoney-observer.yml").read_text(encoding="utf-8")


def test_installer_is_exact_sha_read_only_cloud_runtime():
    assert 'REPO_REF="${REPO_REF:?REPO_REF exact commit SHA is required}"' in INSTALL
    assert "build_cn_cloud_observation" in INSTALL
    assert "build_tencent_kline_url" in INSTALL
    assert "stock-razor-cn-eastmoney.service" in INSTALL
    assert "RuntimeDirectory=stock-razor-cn-eastmoney" in INSTALL
    assert "NoNewPrivileges=true" in INSTALL
    assert "ProtectSystem=strict" in INSTALL
    assert "live_trade" in INSTALL
    assert "order" not in INSTALL.lower()
    assert "trade_context" not in INSTALL.lower()


def test_verifier_requires_real_three_timeframe_cloud_evidence():
    assert 'payload.get("status") == "PASS"' in VERIFY
    assert 'payload.get("provider_policy") == "EASTMONEY_PRIMARY_TENCENT_FALLBACK"' in VERIFY
    assert 'set(payload.get("provider_lineages") or []) == {"eastmoney", "tencent"}' in VERIFY
    assert 'set(frames) == {"1d", "60m", "15m"}' in VERIFY
    assert 'int(frame.get("row_count") or 0) > 0' in VERIFY
    assert 'provider in {"eastmoney", "tencent"}' in VERIFY
    assert 'latest.get("volume_unit") == "PROVIDER_RAW_UNVERIFIED"' in VERIFY
    assert 'latest.get("volume_unit") == "HAND"' in VERIFY
    assert 'frame.get("fallback_from") == "eastmoney"' in VERIFY
    assert 'frame.get("currentness") in {"UNPROVEN", "PROVEN"}' in VERIFY
    assert 'currentness.get("status") in {"PASS", "BLOCKED"}' in VERIFY
    assert 'currentness.get("currentness_proven") is (' in VERIFY
    assert 'qualification.get("status") == "PASS"' in VERIFY
    assert 'qualification.get("timestamp_semantic") == "BAR_END"' in VERIFY
    assert 'qualification.get("currentness_proven") is False' in VERIFY
    assert 'qualification.get("continuity_proven") is False' in VERIFY
    assert 'frame.get("timestamp_semantic") == "BAR_END"' in VERIFY
    assert 'frame.get("timestamp_semantic") == "UNKNOWN"' in VERIFY
    assert 'payload.get("radar_admission") == "BLOCKED"' in VERIFY
    assert 'payload.get("live_trade") is False' in VERIFY
    assert 'CN_EASTMONEY_COMPACT=' in VERIFY
    assert 'latest_label' in VERIFY
    assert 'row_count' in VERIFY
    assert 'cat "$status"' not in VERIFY


def test_workflow_deploys_exact_main_over_ssm_only():
    assert "Deploy Read-Only CN Eastmoney Observer" in WORKFLOW
    assert "actions/checkout@v4" in WORKFLOW
    assert "aws-actions/configure-aws-credentials@v4" in WORKFLOW
    assert "install_cn_eastmoney_observer.sh" in WORKFLOW
    assert "verify_cn_eastmoney_observer.sh" in WORKFLOW
    assert "EASTMONEY_PRIMARY_TENCENT_FALLBACK" in WORKFLOW
    assert '\"intraday_timestamp_semantics_proven\":true' in WORKFLOW
    assert '\"intraday_timestamp_semantics_proven\":false' not in WORKFLOW
    assert 'intraday_currentness_proven\":(true|false)' in WORKFLOW
    assert "CN_EASTMONEY_CLOUD_DEPLOYMENT=PASS" in WORKFLOW
    assert "LIVE_TRADE=NO" in WORKFLOW

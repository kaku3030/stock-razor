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

def test_deploy_binds_exact_sha_and_requires_heartbeat():
    assert "REPO_REF=$REPO_REF" in WORKFLOW
    assert "us_opend_livefeed_heartbeat" in WORKFLOW
    assert '"live_trade":false' in WORKFLOW
    assert "US_OPEND_LIVEFEED_AWS_DEPLOYMENT=PASS" in WORKFLOW

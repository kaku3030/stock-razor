from pathlib import Path


INSTALL = Path("ops/aws/install_cn_radar_worker.sh").read_text(encoding="utf-8")
VERIFY = Path("ops/aws/verify_cn_radar_worker.sh").read_text(encoding="utf-8")
WORKFLOW = Path(".github/workflows/deploy-cn-radar-worker.yml").read_text(encoding="utf-8")


def test_installer_isolated_readonly_worker_contract():
    assert 'SOURCE_REPO_SHA="${SOURCE_REPO_SHA:?SOURCE_REPO_SHA exact CN observation commit SHA is required}"' in INSTALL
    assert "CnObservationRadarWorker" in INSTALL
    assert "PrivateNetwork=true" in INSTALL
    assert "NoNewPrivileges=true" in INSTALL
    assert "ReadOnlyPaths=/run/stock-razor-cn-eastmoney" in INSTALL
    assert "stock-razor-cn-eastmoney.service" in INSTALL
    assert "STOCK_RAZOR_CN_RADAR_POLL_SECONDS=5" in INSTALL
    assert "OpenQuoteContext" not in INSTALL
    assert "urlopen" not in INSTALL
    assert "trade" not in INSTALL.lower().replace("live_trade", "")


def test_verifier_requires_precomputed_three_timeframe_research_state():
    assert 'analysis.get("schema") == "stock_razor_cn_radar_research_v1"' in VERIFY
    assert 'analysis.get("status") == "PASS"' in VERIFY
    assert 'item.get("status") == "RESEARCH_STATE"' in VERIFY
    assert 'item.get("signal_permission") == "record_only"' in VERIFY
    assert '(technical.get("daily") or {}).get("timeframe") == "1d"' in VERIFY
    assert '(technical.get("hourly") or {}).get("timeframe") == "1h"' in VERIFY
    assert '(technical.get("intraday") or {}).get("timeframe") == "15m"' in VERIFY
    assert '"cn_intraday_timestamp_semantics_unproven" in flags' in VERIFY
    assert '"cn_intraday_currentness_unproven" in flags' in VERIFY
    assert 'payload.get("radar_admission") == "BLOCKED"' in VERIFY
    assert 'payload.get("live_trade") is False' in VERIFY


def test_deploy_workflow_discovers_runtime_source_sha_and_uses_exact_worker_sha():
    assert "Deploy Read-Only CN Radar Worker" in WORKFLOW
    assert "latest-observation.json" in WORKFLOW
    assert "CN_SOURCE_SHA=" in WORKFLOW
    assert "install_cn_radar_worker.sh" in WORKFLOW
    assert "verify_cn_radar_worker.sh" in WORKFLOW
    assert "CN_RADAR_WORKER_AWS_DEPLOYMENT=PASS" in WORKFLOW
    assert "LIVE_TRADE=NO" in WORKFLOW

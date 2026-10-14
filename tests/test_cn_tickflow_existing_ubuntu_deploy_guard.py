"""Fixed Ubuntu exception must never authorize another mixed EC2 host."""
from pathlib import Path


def test_ubuntu_target_exception_requires_exact_ec2_and_pre_existing_worker():
    workflow = Path(".github/workflows/deploy-cn-tickflow-research.yml").read_text("utf-8")
    assert 'elif .PlatformType == "Linux" and $id == "i-01738342af3efac72" and $id_match' in workflow
    assert 'PINNED_LINUX_REQUIRES_UBUNTU_OS_PROOF' in workflow
    assert 'test "${ID:-}" = ubuntu' in workflow
    assert '(.PlatformType == "Linux" and $id == "i-01738342af3efac72")' in workflow
    assert 'PLATFORM_NAME_MISMATCH' in workflow
    assert 'CN_TICKFLOW_PINNED_UBUNTU_PROOF=PASS' in workflow
    assert 'test "$(systemctl is-active stock-razor-us-livefeed.service)" = active' in workflow
    assert 'test "$(systemctl is-active stock-razor-mcp.service)" = active' in workflow
    assert 'test "$(systemctl is-active "$unit")" = active' in workflow
    assert 'test "$(systemctl show "$unit" -p WorkingDirectory --value)" = "$repo"' in workflow
    assert 'test -z "$(git -C "$repo" status --porcelain)"' in workflow
    assert "scripts.run_cn_tickflow_research_worker" in workflow
    assert "mode: dry-run" in workflow or "default: dry-run" in workflow
    assert "DEPLOY_CN_TICKFLOW_WORKER" in workflow
    assert "approve_paid_tickflow_ingestion" in workflow
    assert "SOURCE_ARBITER_ADMISSION=BLOCKED" in workflow
    assert "RADAR_ADMISSION=BLOCKED" in workflow
    assert "LIVE_TRADE=NO" in workflow


def test_failed_worker_update_restores_original_unit_revision_as_well_as_code():
    installer = Path("ops/aws/install_cn_tickflow_research.sh").read_text("utf-8")
    assert 'unit_file="/etc/systemd/system/$SERVICE"' in installer
    assert "sr-cn-tickflow-research-unit." in installer
    assert 'cp -p -- "$unit_file" "$unit_backup"' in installer
    assert 'cp -p -- "$unit_backup" "$unit_file"' in installer
    assert 'git -C "$ROOT/repo" checkout --detach "$previous_sha"' in installer
    assert 'systemctl restart "$SERVICE"' in installer
    assert "trap rollback ERR" in installer
    assert 'rm -f -- "$unit_backup"' in installer

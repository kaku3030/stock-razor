"""Protect pinned AWS TickFlow Ubuntu instance proof during deploy preflight."""
from pathlib import Path


def test_pinned_ssm_linux_requires_runtime_ubuntu_os_verification():
    workflow=Path(".github/workflows/deploy-cn-tickflow-research.yml").read_text("utf8")
    assert workflow.count("i-01738342af3efac72") >= 3
    assert 'PINNED_LINUX_REQUIRES_UBUNTU_OS_PROOF' in workflow
    assert '(.PlatformType == "Linux" and $id == "i-01738342af3efac72")' in workflow
    assert '. /etc/os-release' in workflow
    assert 'test "${ID:-}" = ubuntu' in workflow
    assert 'test "$(uname -s)" = Linux' in workflow
    assert "CN_TICKFLOW_PINNED_UBUNTU_PROOF=PASS" in workflow
    assert "test -z \"$(git -C \"$repo\" status --porcelain)\"" in workflow
    assert "stock-razor-us-livefeed.service" in workflow
    assert "stock-razor-mcp.service" in workflow
    assert "CN_TICKFLOW_DEPLOY_CONFIRMATION_REQUIRED" in workflow
    assert "CN_TICKFLOW_PAID_INGESTION_OPT_IN_REQUIRED" in workflow
    assert "RADAR_ADMISSION=BLOCKED" in workflow
    assert "LIVE_TRADE=NO" in workflow


def test_unpinned_other_linux_not_whitelisted():
    workflow=Path(".github/workflows/deploy-cn-tickflow-research.yml").read_text("utf8")
    assert 'elif .PlatformType == "Linux" and $id == "i-01738342af3efac72" and $id_match' in workflow
    assert '[[ "$GITHUB_REF" == refs/heads/main && "$GITHUB_ACTOR" == "$GITHUB_REPOSITORY_OWNER" ]]' in workflow

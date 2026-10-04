from pathlib import Path

SCRIPT = Path("ops/aws/install_futures_runtime.sh").read_text()


def test_deploy_requires_exact_repo_ref_and_detached_checkout():
    assert 'REPO_REF="${REPO_REF:?REPO_REF exact commit SHA is required}"' in SCRIPT
    assert 'checkout --detach "$REPO_REF"' in SCRIPT
    assert 'rev-parse HEAD' in SCRIPT


def test_futures_runtime_is_separate_and_read_only():
    assert 'stock-razor-futures.service' in SCRIPT
    assert 'stock-razor-mcp.service' not in SCRIPT
    assert '"live_trade": False' in SCRIPT
    assert '"cloud_runtime_verified": False' in SCRIPT
    assert '"pc_off_verified": False' in SCRIPT


def test_service_has_basic_systemd_hardening():
    for directive in ("NoNewPrivileges=true", "PrivateTmp=true", "ProtectSystem=strict", "ProtectHome=true"):
        assert directive in SCRIPT

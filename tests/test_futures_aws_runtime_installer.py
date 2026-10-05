from pathlib import Path

SCRIPT = Path("ops/aws/install_futures_runtime.sh").read_text()


def test_deploy_requires_exact_repo_ref_and_detached_checkout():
    assert 'REPO_REF="${REPO_REF:?REPO_REF exact commit SHA is required}"' in SCRIPT
    assert 'checkout --detach "$REPO_REF"' in SCRIPT
    assert 'rev-parse HEAD' in SCRIPT


def test_futures_runtime_is_separate_and_read_only():
    assert 'stock-razor-futures.service' in SCRIPT
    assert 'systemctl restart stock-razor-mcp.service' not in SCRIPT
    assert 'systemctl stop stock-razor-mcp.service' not in SCRIPT
    assert 'systemctl disable stock-razor-mcp.service' not in SCRIPT
    assert '"live_trade": False' in SCRIPT
    assert '"cloud_runtime_verified": False' in SCRIPT
    assert '"pc_off_verified": False' in SCRIPT


def test_service_has_basic_systemd_hardening():
    for directive in ("NoNewPrivileges=true", "PrivateTmp=true", "ProtectSystem=strict", "ProtectHome=true"):
        assert directive in SCRIPT


def test_runtime_uses_fail_closed_session_policy_and_generation_rollover():
    assert "FuturesSessionPolicy()" in SCRIPT
    assert "observer.rollover_generation(generation" in SCRIPT
    assert "controller_generation=generation)" not in SCRIPT.split("observer = FuturesRuntimeObserver", 1)[1].split("worker =", 1)[0]


def test_runtime_reports_peak_rss_without_extra_dependency():
    assert "import resource" in SCRIPT
    assert "resource.getrusage(resource.RUSAGE_SELF).ru_maxrss" in SCRIPT
    assert '"rss_peak_kib": rss_peak_kib' in SCRIPT
    assert "psutil" not in SCRIPT


def test_runtime_bounds_each_yahoo_fetch_to_recent_window():
    script = SCRIPT
    assert "from datetime import datetime, timedelta, timezone" in script
    assert "def fetch_recent(root, timeframe, *, observed_at_utc):" in script
    assert "start = end - timedelta(hours=2)" in script
    assert "start=start.isoformat()" in script
    assert "end=end.isoformat()" in script
    assert "fetch=fetch_recent" in script

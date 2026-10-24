"""Run the installer's real publication seams without opening a broker session."""

import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time

import pytest

from src.services.live_feed.runtime_publication import write_runtime_json
from src.services.stock_radar_v2.systemd_notify import notify_systemd
from data_provider.us_canonical_runtime_reader import read_us_livefeed_health


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = (ROOT / "ops/aws/install_us_opend_livefeed.sh").read_text()
RUNTIME = INSTALLER.split('cat >"$INSTALL_ROOT/run.py" <<\'PY\'\n', 1)[1].split('\nPY\n', 1)[0]


def publication_namespace(path):
    functions = [n for n in ast.parse(RUNTIME).body
                 if isinstance(n, ast.FunctionDef)
                 and n.name in {"publish", "publish_runtime_heartbeat", "publish_startup_heartbeat"}]
    namespace = {
        "write_runtime_json": write_runtime_json, "notify_systemd": notify_systemd,
        "status_path": str(path), "runtime_id": "new-runtime", "repo_sha": "a" * 40,
        "host_id": "test-host", "CODES": ("US.QQQ",), "datetime": datetime,
        "timezone": timezone, "runtime_ready_notified": False,
        "canonical_snapshot_path": str(path.with_name("canonical.json")),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "embedded-publication", "exec"), namespace)
    return namespace


def test_connection_stall_has_blocked_startup_evidence_without_ready(tmp_path):
    """A real process stalls at the actual constructor position, after startup evidence."""
    tree = ast.parse(RUNTIME)
    startup = [n for n in tree.body if isinstance(n, ast.Expr)
               and isinstance(n.value, ast.Call)
               and isinstance(n.value.func, ast.Name)
               and n.value.func.id == "publish_startup_heartbeat"]
    assert len(startup) == 1
    constructor = next(n for n in tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "ctx" for t in n.targets))
    assert startup[0].lineno < constructor.lineno
    path = tmp_path / "heartbeat.json"
    namespace = publication_namespace(path)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"publish", "publish_runtime_heartbeat", "publish_startup_heartbeat"}]
    script = (
        "from datetime import datetime,timezone\nimport threading\n"
        "from src.services.live_feed.runtime_publication import write_runtime_json\n"
        "def notify_systemd(*fields): raise AssertionError('unexpected startup READY')\n"
        f"status_path={str(path)!r}\nruntime_id='new-runtime'\nrepo_sha={'a' * 40!r}\n"
        "host_id='test-host'\nCODES=('US.QQQ',)\nruntime_ready_notified=False\n"
        f"canonical_snapshot_path={namespace['canonical_snapshot_path']!r}\n"
        "class FT:\n def OpenQuoteContext(self,**kwargs): threading.Event().wait()\nft=FT()\n"
        + ast.unparse(ast.Module(body=functions + startup + [constructor], type_ignores=[]))
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    process = subprocess.Popen([sys.executable, "-c", script], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not path.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert process.poll() is None
        payload = json.loads(path.read_text())
        assert payload["controller_lifecycle"] == "STARTING"
        assert payload["startup_phase"] == "CONNECTING_OPEND"
        assert payload["sequence"] == 0
        assert payload["runtime_instance_id"] == "new-runtime"
        assert payload["subscribed"] == []
        assert payload["delivery_mode"] == "UNKNOWN"
        assert payload["bar_closure"] == "UNPROVEN"
        assert payload["radar_admission"] == "BLOCKED"
        assert payload["live_trade"] is False
        assert payload["can_confirm_signal"] is False
    finally:
        process.kill()
        process.communicate(timeout=5)


def test_ready_and_watchdog_follow_successful_full_heartbeat(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.json"
    socket_path = str(tmp_path / "notify.sock")
    try:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    except PermissionError:
        pytest.skip("runtime policy denies Unix sockets; exercised by Linux CI")
    with server:
        server.bind(socket_path)
        server.settimeout(0.2)
        monkeypatch.setenv("NOTIFY_SOCKET", socket_path)
        namespace = publication_namespace(path)
        namespace["publish_runtime_heartbeat"]({"sequence": 1})
        first = server.recv(4096).decode()
        assert "READY=1" in first and "WATCHDOG=1" in first
        assert json.loads(path.read_text()) == {"sequence": 1}
        namespace["publish_runtime_heartbeat"]({"sequence": 2})
        second = server.recv(4096).decode()
        assert "WATCHDOG=1" in second and "READY=1" not in second
        assert json.loads(path.read_text()) == {"sequence": 2}


def test_publication_failure_never_notifies_ready_or_watchdog(tmp_path):
    path = tmp_path / "heartbeat.json"
    namespace = publication_namespace(path)
    notifications = []
    namespace["notify_systemd"] = lambda *fields: notifications.append(fields)

    def fail_write(*args):
        raise PermissionError("injected publication failure")

    namespace["write_runtime_json"] = fail_write
    with pytest.raises(PermissionError):
        namespace["publish_runtime_heartbeat"]({"sequence": 1})
    assert notifications == []
    assert namespace["runtime_ready_notified"] is False


def test_notification_order_follows_each_completed_publication(tmp_path):
    path = tmp_path / "heartbeat.json"
    namespace = publication_namespace(path)
    notifications = []

    def observe(*fields):
        notifications.append((json.loads(path.read_text())["sequence"], fields))

    namespace["notify_systemd"] = observe
    namespace["publish_runtime_heartbeat"]({"sequence": 1})
    namespace["publish_runtime_heartbeat"]({"sequence": 2})
    assert notifications[0][0] == 1 and "READY=1" in notifications[0][1]
    assert notifications[1][0] == 2 and "READY=1" not in notifications[1][1]
    assert all("WATCHDOG=1" in fields for _, fields in notifications)


def test_starting_heartbeat_is_visible_but_never_healthy_or_realtime(tmp_path):
    path = tmp_path / "heartbeat.json"
    namespace = publication_namespace(path)
    namespace["publish_startup_heartbeat"]()
    result = read_us_livefeed_health(
        status_path=str(path), snapshot_path=str(tmp_path / "missing-canonical.json"),
    )
    assert result["status"] == "DEGRADED"
    assert result["ok"] is False
    assert result["controller_lifecycle"] == "STARTING"
    assert result["realtime_delivery_evidence"] is False
    assert result["bar_closure_proven"] is False
    assert result["radar_admission"] == "BLOCKED"
    assert result["live_trade"] is False


def test_systemd_supervises_startup_and_runtime_without_loosening_restart_gate():
    assert any(isinstance(node, ast.ImportFrom)
               and node.module == "src.services.stock_radar_v2.systemd_notify"
               and any(alias.name == "notify_systemd" for alias in node.names)
               for node in ast.parse(RUNTIME).body)
    assert "Type=notify\nNotifyAccess=main" in INSTALLER
    assert "TimeoutStartSec=900s" in INSTALLER
    assert "TimeoutStopSec=15s" in INSTALLER
    assert "WatchdogSec=300s" in INSTALLER
    assert "RestartSec=30" in INSTALLER
    assert "StartLimitIntervalSec=300" in INSTALLER
    assert "StartLimitBurst=5" in INSTALLER
    assert "require_safe_us_restart_window" in INSTALLER
    assert "US_SESSION_SAFETY_WINDOW_BLOCKED" in INSTALLER


def test_deployment_wait_covers_service_startup_and_verification_budget():
    workflow = (ROOT / ".github/workflows/deploy-us-opend-livefeed.yml").read_text()
    verifier = (ROOT / "ops/aws/verify_us_opend_livefeed.sh").read_text()
    startup = int(re.search(r"TimeoutStartSec=(\d+)s", INSTALLER)[1])
    stop = int(re.search(r"TimeoutStopSec=(\d+)s", INSTALLER)[1])
    polls = int(re.search(r"seq 1 (\d+)", workflow)[1])
    verifier_polls = int(re.search(r"seq 1 (\d+)", verifier)[1])
    job_minutes = int(re.search(r"timeout-minutes: (\d+)", workflow)[1])
    assert polls * 5 > startup + stop + verifier_polls * 5
    assert job_minutes * 60 > polls * 5 + 60
    # SSM TimeoutSeconds bounds delivery before execution starts, rather than
    # the duration of an already-running service startup. Keep it unchanged.
    assert "--timeout-seconds 600" in workflow
    assert 'inputs.expected_main_sha == github.sha' in workflow
    assert 'python3 scripts/guard_us_livefeed_restart_window.py' in workflow

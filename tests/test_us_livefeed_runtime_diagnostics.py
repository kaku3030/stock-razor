"""Bounded private-host diagnostics must survive the public-safe projector."""
import json

from scripts.sanitize_ssm_probe_output import project


def test_runtime_diagnostics_projection_preserves_only_fixed_typed_evidence():
    raw = {
        "probe": "us_livefeed_status",
        "runtime_diagnostics": {
            "systemd_query": "PASS", "active_state": "ACTIVE", "sub_state": "RUNNING",
            "result": "EXIT_CODE", "exit_status": 1, "restarts": 47,
            "process_start_monotonic_us": 123456789,
            "process_elapsed_seconds": 42,
            "installed_repo_sha": "a" * 40, "runner_sha256": "b" * 64,
            "files": {"heartbeat": {"state": "MISSING", "mode": None}},
            "journal_query": "PASS", "journal_counts": {"PERMISSION_DENIED": 3},
            "journal_raw": "PRIVATE-ACCOUNT /root/token secret=value",
            "process_command": "PRIVATE-ACCOUNT password=value",
        },
    }
    output = "\n".join(project(json.dumps(raw)))
    assert '"runtime_diagnostics"' in output
    assert '"PERMISSION_DENIED":3' in output
    assert '"restarts":47' in output
    assert "PRIVATE-ACCOUNT" not in output
    assert "secret=value" not in output
    assert "process_command" not in output


def test_fixed_host_collection_classifies_private_errors_without_forwarding_them(tmp_path, monkeypatch):
    from scripts import us_livefeed_runtime_diagnostics as diag

    monkeypatch.setattr(diag, "ROOT", tmp_path)
    monkeypatch.setattr(diag, "FILES", {
        "heartbeat": tmp_path / "heartbeat.json",
        "snapshot": tmp_path / "snapshot.json",
        "daily": tmp_path / "daily.json",
    })
    (tmp_path / "run.py").write_text("# exact private installed runtime\n")
    (tmp_path / "snapshot.json").write_text("{broken")
    (tmp_path / "snapshot.json").chmod(0o640)
    started = diag.time.monotonic_ns() // 1000 - 42_000_000
    commands = []

    def fixed_command(args):
        commands.append(args)
        if args[0] == "systemctl":
            return "PASS", ("LoadState=loaded\nActiveState=active\nSubState=running\n"
                            "Result=exit-code\nExecMainStatus=1\nNRestarts=47\n"
                            f"ExecMainStartTimestampMonotonic={started}\n"
                            f"WorkingDirectory={tmp_path / 'repo'}\n")
        if args[0] == "git":
            return "PASS", "a" * 40 + "\n"
        return "PASS", ("PermissionError: /root/PRIVATE_TOKEN secret=value\n"
                        "FileNotFoundError: /private/ACCOUNT_ID\n"
                        "ModuleNotFoundError: PRIVATE_MODULE\n")

    monkeypatch.setattr(diag, "_command", fixed_command)
    evidence = diag.collect_runtime_diagnostics()
    assert evidence["active_state"] == "ACTIVE"
    assert evidence["result"] == "EXIT_CODE"  # Last exit is not current liveness.
    assert evidence["restarts"] == 47
    assert evidence["process_elapsed_seconds"] in (42, 43)
    assert evidence["working_directory"] == "MATCH"
    assert evidence["files"]["heartbeat"] == {"state": "MISSING", "mode": None}
    assert evidence["files"]["snapshot"] == {"state": "REGULAR", "mode": "0640"}
    assert evidence["journal_counts"]["PERMISSION_DENIED"] == 1
    assert evidence["journal_counts"]["FILE_MISSING"] == 1
    projected = "\n".join(project(json.dumps({"runtime_diagnostics": evidence})))
    for raw in ("/root", "PRIVATE_TOKEN", "secret=value", "ACCOUNT_ID", "PRIVATE_MODULE", str(tmp_path)):
        assert raw not in projected
    assert [args[0] for args in commands] == ["systemctl", "git", "journalctl", "ss", "ps", "/opt/stock-razor-opend-client/venv/bin/python", "/opt/stock-razor-opend-client/venv/bin/python"]
    assert not any("restart" in args or "start" in args for args in commands)


def test_unavailable_host_queries_remain_unknown(tmp_path, monkeypatch):
    from scripts import us_livefeed_runtime_diagnostics as diag

    monkeypatch.setattr(diag, "ROOT", tmp_path)
    monkeypatch.setattr(diag, "_command", lambda _args: ("TIMEOUT", "untrusted private message"))
    evidence = diag.collect_runtime_diagnostics()
    assert evidence["systemd_query"] == "TIMEOUT"
    assert evidence["active_state"] == "UNKNOWN"
    assert evidence["journal_query"] == "TIMEOUT"
    assert evidence["installed_repo_sha"] == "UNAVAILABLE"
    assert "private message" not in json.dumps(evidence)


def test_real_eof_before_process_exit_is_killed_at_deadline():
    import sys
    import time
    from scripts.us_livefeed_runtime_diagnostics import _command

    started = time.monotonic()
    state, output = _command([sys.executable, "-c", "import os,time;os.close(1);time.sleep(10)"])
    assert state == "TIMEOUT"
    assert output == ""
    assert time.monotonic() - started < 5


def test_real_oversized_command_output_is_bounded():
    import sys
    from scripts.us_livefeed_runtime_diagnostics import _command

    state, output = _command([sys.executable, "-c", "print('x'*100000)"], limit=1000)
    assert state == "TRUNCATED"
    assert len(output.encode()) == 1000


def test_adversarial_nested_fields_cannot_leak_or_promote():
    from scripts.us_livefeed_runtime_diagnostics import sanitize_runtime_diagnostics

    evidence = sanitize_runtime_diagnostics({
        "active_state": "PRIVATE_SECRET", "exit_status": True, "restarts": -1,
        "installed_repo_sha": "/root/secret", "runner_sha256": "password=value",
        "files": {"private_name": {"state": "REGULAR", "mode": "0644"},
                  "heartbeat": {"state": "REGULAR", "mode": "/private"}},
        "journal_counts": {"PRIVATE_SECRET": 7, "FILE_MISSING": True},
        "process_command": "secret=value",
    })
    assert evidence == {"installed_repo_sha": "UNAVAILABLE", "runner_sha256": "UNAVAILABLE",
                        "files": {"heartbeat": {"state": "REGULAR", "mode": None}},
                        "journal_counts": {}}


def test_gateway_presence_is_observation_not_quote_health(tmp_path, monkeypatch):
    from scripts import us_livefeed_runtime_diagnostics as diag

    monkeypatch.setattr(diag, "ROOT", tmp_path)

    def command(args):
        if args[0] == "ss":
            return "PASS", "LISTEN 0 128 127.0.0.1:11111 0.0.0.0:*\n"
        if args[0] == "ps":
            return "PASS", "OpenD\nPRIVATE_PROCESS_NAME\n"
        return "UNAVAILABLE", ""

    monkeypatch.setattr(diag, "_command", command)
    observed = diag.collect_runtime_diagnostics()
    assert observed["opend_listener"] == "LOOPBACK_BIND_OBSERVED"
    assert observed["opend_process"] == "PRESENT"
    result = "\n".join(project(json.dumps({"runtime_diagnostics": observed})))
    assert "PRIVATE_PROCESS_NAME" not in result
    assert '"opend_process":"PRESENT"' in result
    assert "opend_reachable" not in result


def test_gateway_absence_and_failed_queries_remain_distinct(tmp_path, monkeypatch):
    from scripts import us_livefeed_runtime_diagnostics as diag

    monkeypatch.setattr(diag, "ROOT", tmp_path)
    monkeypatch.setattr(diag, "_command", lambda _args: ("PASS", ""))
    absent = diag.collect_runtime_diagnostics()
    assert absent["opend_listener"] == "NO_LISTENER"
    assert absent["opend_process"] == "ABSENT"
    monkeypatch.setattr(diag, "_command", lambda _args: ("TIMEOUT", ""))
    unknown = diag.collect_runtime_diagnostics()
    assert unknown["opend_listener"] == "UNKNOWN"
    assert unknown["opend_process"] == "UNKNOWN"


def test_legacy_import_probe_reports_fixed_class_without_exception_text(monkeypatch):
    import subprocess
    import sys
    from scripts import us_livefeed_runtime_diagnostics as diag

    # Execute actual child code; secret-bearing exceptions stay private.
    setup = "import builtins\noriginal_import=builtins.__import__\ndef guard(name,*a,**kw):\n if name.startswith('src.services.stock_radar_v2'):\n  raise ModuleNotFoundError('PRIVATE_ACCOUNT secret=hidden',name='yaml')\n return original_import(name,*a,**kw)\nbuiltins.__import__=guard\n"
    result = subprocess.run([sys.executable, "-c", setup + diag.LEGACY_IMPORT_PROBE_CODE],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    assert result.stdout == "MISSING_YAML\n"
    assert result.stderr == ""
    safe = diag.sanitize_runtime_diagnostics({"legacy_notify_import": result.stdout.strip()})
    assert safe["legacy_notify_import"] == "MISSING_YAML"
    assert "legacy_notify_import" not in diag.sanitize_runtime_diagnostics({
        "legacy_notify_import": "PRIVATE_ACCOUNT secret=hidden"})


def test_connect_error_families_use_pinned_sdk_messages_without_leaking(monkeypatch, tmp_path):
    from scripts import us_livefeed_runtime_diagnostics as diag
    monkeypatch.setattr(diag, "ROOT", tmp_path)

    def command(args):
        if args[0] == "journalctl":
            return "PASS", "\n".join([
                "Connect fail: conn=PRIVATE_ACCOUNT; msg=ECONNREFUSED; context=secret",
                "Connect fail: conn=private; msg=Timeout; context=secret",
                "Connect fail: conn=private; msg=EACCES; context=secret",
                "init connect fail: conn=private; msg=secret",
                "start operation timed out. Terminating.",
            ])
        return "UNAVAILABLE", ""
    monkeypatch.setattr(diag, "_command", command)
    evidence = diag.collect_runtime_diagnostics()
    for key in ("CONNECT_REFUSED", "CONNECT_TIMEOUT", "CONNECT_PERMISSION", "HANDSHAKE_FAILURE", "STARTUP_TIMEOUT"):
        assert evidence["journal_counts"][key] == 1
    assert evidence["journal_counts"]["CONNECT_RESET"] == 0
    assert "PRIVATE_ACCOUNT" not in json.dumps(evidence)
    assert "secret" not in json.dumps(evidence)


def test_listener_owner_must_belong_to_fixed_endpoint_and_remain_categorical():
    from scripts.us_livefeed_runtime_diagnostics import classify_listener_owner, sanitize_runtime_diagnostics
    prefix = "LISTEN 0 128 127.0.0.1:11111 0.0.0.0:* "
    for name, expected in (("OpenD", "OPEND"), ("FutuOpenD", "OPEND"), ("python3", "PYTHON"), ("sshd", "SSH"), ("PRIVATE_ACCOUNT", "OTHER")):
        assert classify_listener_owner(prefix + 'users:(("' + name + '",pid=123,fd=4))') == expected
    assert classify_listener_owner(prefix) == "UNKNOWN"
    assert classify_listener_owner(prefix.replace(":11111", ":22222") + 'users:(("OpenD",pid=123,fd=4))') == "MISSING"
    safe = sanitize_runtime_diagnostics({"opend_listener_owner": "PRIVATE_ACCOUNT", "owner_pid": 123})
    assert "opend_listener_owner" not in safe
    assert "owner_pid" not in safe


def test_offline_init_pack_executes_serialization_without_a_context():
    import subprocess
    import sys
    from scripts import us_livefeed_runtime_diagnostics as diag

    setup = """import sys,types
ft=types.ModuleType('futu')
ft.RET_OK=0
class Config:
    get_client_ver=staticmethod(lambda: 1011)
    get_proto_fmt=staticmethod(lambda: 0)
ft.SysConfig=Config
class ForbiddenContext:
    def __init__(self,*a,**kw):
        raise AssertionError('provider context forbidden')
ft.OpenQuoteContext=ForbiddenContext
query=types.ModuleType('futu.quote.quote_query')
class InitConnect:
    @staticmethod
    def pack_req(**kw):
        assert kw['client_id']=='readonly-diagnostic'
        assert kw['is_encrypt'] is False
        return 0,'PRIVATE_SECRET',b'packet',1001,1
query.InitConnect=InitConnect
sys.modules['futu']=ft
sys.modules['futu.quote.quote_query']=query
"""
    result = subprocess.run([sys.executable, "-c", setup + diag.OFFLINE_INIT_PACK_CODE],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0
    assert result.stdout == "PASS\n"
    assert result.stderr == ""
    safe = diag.sanitize_runtime_diagnostics({"offline_init_pack": "PRIVATE_SECRET"})
    assert "offline_init_pack" not in safe


def test_gateway_startup_config_is_bound_to_endpoint_owner_and_never_leaks(tmp_path, monkeypatch):
    from scripts import us_livefeed_runtime_diagnostics as diag
    proc = tmp_path / "proc" / "123"
    proc.mkdir(parents=True)
    binary = tmp_path / "OpenD"
    binary.write_text("binary-placeholder")
    (proc / "exe").symlink_to(binary)
    config = tmp_path / "private.xml"
    config.write_text('<futu_opend><api_port>22222</api_port><telnet_port>11111</telnet_port><rsa_private_key>/PRIVATE_KEY</rsa_private_key><login_pwd>PRIVATE_PASSWORD</login_pwd></futu_opend>')
    (proc / "cmdline").write_bytes((str(binary) + "\0-cfg_file=" + str(config) + "\0-login_pwd=PRIVATE_PASSWORD\0").encode())
    monkeypatch.setattr(diag, "PROC_ROOT", tmp_path / "proc")
    listener = 'LISTEN 0 128 127.0.0.1:11111 0.0.0.0:* users:(("OpenD",pid=123,fd=4))'
    observed = diag.gateway_config_metadata(listener)
    assert observed == {"gateway_config": "PARSED_STARTUP_CANDIDATE", "gateway_api_port": "MISMATCH", "gateway_telnet_port": "CONFLICT", "gateway_rsa": "CONFIGURED"}
    assert "PRIVATE" not in json.dumps(observed)
    (proc / "cmdline").write_bytes((str(binary) + "\0-cfg_file=" + str(config) + "\0-api_port=11111\0").encode())
    assert diag.gateway_config_metadata(listener)["gateway_api_port"] == "MATCH"
    config.write_text('<!DOCTYPE x [<!ENTITY test "private">]><futu_opend/>')
    assert diag.gateway_config_metadata(listener) == {"gateway_config": "INVALID"}
    assert diag.gateway_config_metadata(listener.replace('"OpenD"', '"python3"')) == {"gateway_config": "UNKNOWN"}

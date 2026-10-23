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
    assert [args[0] for args in commands] == ["systemctl", "git", "journalctl"]
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

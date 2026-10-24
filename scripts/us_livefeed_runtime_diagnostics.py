"""Read-only fixed-host evidence; raw command/journal text never leaves this module."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import time

UNIT = "stock-razor-us-livefeed.service"
ROOT = Path("/opt/stock-razor-us-livefeed")
FILES = {name: Path("/run/stock-razor-us-livefeed") / filename for name, filename in (
    ("heartbeat", "latest-heartbeat.json"),
    ("snapshot", "canonical-market-snapshot.json"),
    ("daily", "daily-history.json"),
)}
ENUMS = {
    "systemd_query": {"PASS", "UNAVAILABLE", "TIMEOUT", "TRUNCATED"},
    "active_state": {"ACTIVE", "INACTIVE", "ACTIVATING", "DEACTIVATING", "FAILED", "RELOADING", "UNKNOWN"},
    "sub_state": {"RUNNING", "DEAD", "FAILED", "AUTO_RESTART", "START_PRE", "START", "START_POST", "EXITED", "STOP", "STOP_SIGTERM", "STOP_SIGKILL", "STOP_POST", "RELOAD", "CLEANING", "UNKNOWN"},
    "result": {"SUCCESS", "EXIT_CODE", "SIGNAL", "CORE_DUMP", "TIMEOUT", "WATCHDOG", "START_LIMIT_HIT", "RESOURCES", "PROTOCOL", "OOM_KILL", "UNKNOWN"},
    "journal_query": {"PASS", "UNAVAILABLE", "TIMEOUT", "TRUNCATED"},
    "load_state": {"LOADED", "NOT_FOUND", "MASKED", "ERROR", "BAD_SETTING", "UNKNOWN"},
    "working_directory": {"MATCH", "MISMATCH", "UNKNOWN"},
    "opend_listener": {"LOOPBACK_BIND_OBSERVED", "OTHER_BIND_OBSERVED", "NO_LISTENER", "UNKNOWN"},
    "opend_process": {"PRESENT", "ABSENT", "UNKNOWN"},
    "opend_listener_owner": {"OPEND", "PYTHON", "SSH", "OTHER", "MISSING", "UNKNOWN"},
    "legacy_notify_import": {"PASS", "MISSING_YAML", "MISSING_DEPENDENCY", "IMPORT_ERROR", "TIMEOUT", "UNAVAILABLE", "TRUNCATED"},
}
PATTERNS = {
    "FILE_MISSING": r"FileNotFoundError",
    "PERMISSION_DENIED": r"PermissionError|Permission denied|Read-only file system",
    "DISK_FULL": r"No space left on device",
    "INVALID_JSON": r"JSONDecodeError",
    "NAME_ERROR": r"NameError", "TYPE_ERROR": r"TypeError",
    "VALUE_ERROR": r"ValueError", "RUNTIME_ERROR": r"RuntimeError",
    "ATTRIBUTE_ERROR": r"AttributeError",
    "INVALID_SERIALIZATION": r"Out of range float values|not JSON serializable",
    "IMPORT_FAILURE": r"ModuleNotFoundError|ImportError",
    "CONNECT_FAILURE": r"ConnectionRefusedError|Connection refused|connect fail",
    "CONNECT_REFUSED": r"connect fail.*(?:ECONNREFUSED|Connection refused)",
    "CONNECT_TIMEOUT": r"connect fail.*(?:ETIMEDOUT|Timeout)",
    "CONNECT_RESET": r"connect fail.*(?:ECONNRESET|Connection reset)",
    "CONNECT_PERMISSION": r"connect fail.*(?:EACCES|EPERM|Permission denied)",
    "CONNECT_UNREACHABLE": r"connect fail.*(?:ENETUNREACH|EHOSTUNREACH)",
    "CONNECT_FD_LIMIT": r"connect fail.*(?:EMFILE|ENFILE)",
    "HANDSHAKE_FAILURE": r"init connect fail",
    "STARTUP_TIMEOUT": r"start operation timed out|Failed with result 'timeout'",
    "CALLBACK_STARVATION": r"US_OPEND_STARTUP_CALLBACK_STARVATION",
    "UNCLASSIFIED_TRACEBACK": r"Traceback \(most recent call last\)",
}


LEGACY_IMPORT_PROBE_CODE = """import contextlib,io,sys
sys.path.insert(0,'/opt/stock-razor-us-livefeed/repo')
try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from src.services.stock_radar_v2.systemd_notify import notify_systemd
    result='PASS'
except ModuleNotFoundError as exc:
    result='MISSING_YAML' if exc.name=='yaml' else 'MISSING_DEPENDENCY'
except Exception:
    result='IMPORT_ERROR'
print(result)
"""


def sanitize_runtime_diagnostics(value):
    """Second boundary: reject arbitrary fields, log text, hashes and numeric types."""
    if not isinstance(value, dict):
        return {}
    out = {k: v for k, allowed in ENUMS.items()
           if isinstance((v := value.get(k)), str) and v in allowed}
    for key, maximum in (("exit_status", 65535), ("restarts", 1000000),
                         ("process_start_monotonic_us", 315360000000000),
                         ("process_elapsed_seconds", 315360000)):
        v = value.get(key)
        if type(v) is int and 0 <= v <= maximum:
            out[key] = v
    for key, length in (("installed_repo_sha", 40), ("runner_sha256", 64)):
        v = value.get(key)
        out[key] = v if isinstance(v, str) and re.fullmatch("[a-f0-9]{" + str(length) + "}", v) else "UNAVAILABLE"
    files = value.get("files")
    if isinstance(files, dict):
        out["files"] = {}
        for key in FILES:
            item = files.get(key)
            if not isinstance(item, dict):
                continue
            state = item.get("state")
            if state not in ("REGULAR", "MISSING", "UNREADABLE", "OTHER"):
                continue
            mode = item.get("mode")
            out["files"][key] = {"state": state, "mode": mode if isinstance(mode, str) and re.fullmatch("[0-7]{4}", mode) else None}
    counts = value.get("journal_counts")
    if isinstance(counts, dict):
        out["journal_counts"] = {k: v for k in PATTERNS
                                 if type(v := counts.get(k)) is int and 0 <= v <= 200}
    return out


def _command(args, *, limit=131072):
    """No shell, bounded bytes/deadline, and no command stderr in public output."""
    proc = None
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        data = bytearray()
        state = "PASS"
        deadline = time.monotonic() + 3
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    state = "TIMEOUT"
                    break
                chunk = os.read(proc.stdout.fileno(), min(8192, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limit:
                    state = "TRUNCATED"
                    break
        if state != "PASS":
            proc.kill()
        try:
            proc.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            state = "TIMEOUT"
            proc.kill()
            proc.wait(timeout=1)
        if state == "PASS" and proc.returncode:
            state = "UNAVAILABLE"
        return state, data[:limit].decode("utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return "UNAVAILABLE", ""
    finally:
        # Never use Popen.__exit__: an EOF-producing child may still be alive.
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            proc.stdout.close()


def _file_state(path):
    try:
        info = path.lstat()
        return {"state": "REGULAR" if stat.S_ISREG(info.st_mode) else "OTHER",
                "mode": format(stat.S_IMODE(info.st_mode), "04o")}
    except FileNotFoundError:
        return {"state": "MISSING", "mode": None}
    except OSError:
        return {"state": "UNREADABLE", "mode": None}


def classify_listener_owner(text):
    """Bind a process category to the fixed endpoint, never publish PID/argv."""
    lines = [line for line in text.splitlines()
             if len(parts := line.split()) >= 5 and parts[3].endswith(":11111")]
    if not lines:
        return "MISSING"
    names = [name for line in lines for name in re.findall(r'\("([^"\n]+)",pid=', line)]
    if not names:
        return "UNKNOWN"  # ss can omit owner metadata without privilege.
    categories = {"OPEND" if name in {"OpenD", "FutuOpenD", "moomoo_OpenD"}
                  else "PYTHON" if name in {"python", "python3"}
                  else "SSH" if name in {"ssh", "sshd"} else "OTHER"
                  for name in names}
    return next(iter(categories)) if len(categories) == 1 else "UNKNOWN"


def collect_runtime_diagnostics():
    properties = "LoadState,ActiveState,SubState,Result,ExecMainStatus,NRestarts,ExecMainStartTimestampMonotonic,WorkingDirectory"
    query, text = _command(["systemctl", "show", UNIT, "--no-pager", "--property=" + properties])
    props = dict(line.split("=", 1) for line in text.splitlines() if "=" in line) if query == "PASS" else {}
    out = {"systemd_query": query, "files": {k: _file_state(v) for k, v in FILES.items()}}
    for key, prop in (("load_state", "LoadState"), ("active_state", "ActiveState"), ("sub_state", "SubState"), ("result", "Result")):
        out[key] = props.get(prop, "UNKNOWN").upper().replace("-", "_")
    directory = props.get("WorkingDirectory")
    out["working_directory"] = "UNKNOWN" if not directory else ("MATCH" if directory == str(ROOT / "repo") else "MISMATCH")
    for key, prop in (("exit_status", "ExecMainStatus"), ("restarts", "NRestarts"),
                      ("process_start_monotonic_us", "ExecMainStartTimestampMonotonic")):
        v = props.get(prop, "")
        if re.fullmatch("[0-9]{1,15}", v):
            out[key] = int(v)
    started = out.get("process_start_monotonic_us", 0)
    elapsed_us = time.monotonic_ns() // 1000 - started
    if started > 0 and elapsed_us >= 0:
        out["process_elapsed_seconds"] = elapsed_us // 1000000
    query, text = _command(["git", "-C", str(ROOT / "repo"), "rev-parse", "HEAD"])
    out["installed_repo_sha"] = text.strip() if query == "PASS" else "UNAVAILABLE"
    runner = ROOT / "run.py"
    try:
        if _file_state(runner)["state"] == "REGULAR":
            with runner.open("rb") as handle:
                content = handle.read(4000001)
            if len(content) <= 4000000:
                out["runner_sha256"] = hashlib.sha256(content).hexdigest()
    except OSError:
        pass
    query, text = _command(["journalctl", "-u", UNIT, "--since=-24h", "-n", "200", "--no-pager", "--quiet", "--output=cat"])
    out["journal_query"] = query
    # Counts describe a bounded recent journal sample, never a proven root cause.
    out["journal_counts"] = {name: sum(bool(re.search(pattern, line, re.I)) for line in text.splitlines()[:200])
                             for name, pattern in PATTERNS.items()}
    # Observe the existing fixed gateway endpoint without opening a provider
    # connection. A listening port or process never certifies usable quotes.
    query, text = _command(["ss", "-ltnpH"])
    out["opend_listener"] = "UNKNOWN"
    out["opend_listener_owner"] = "UNKNOWN"
    if query == "PASS":
        out["opend_listener_owner"] = classify_listener_owner(text)
        addresses = [parts[3] for line in text.splitlines()
                     if len(parts := line.split()) >= 5 and parts[3].endswith(":11111")]
        out["opend_listener"] = (
            "LOOPBACK_BIND_OBSERVED"
            if any(address.rsplit(":", 1)[0] in {"127.0.0.1", "0.0.0.0", "*"}
                   for address in addresses)
            else "OTHER_BIND_OBSERVED" if addresses else "NO_LISTENER"
        )
    query, text = _command(["ps", "-eo", "comm="])
    out["opend_process"] = (
        "PRESENT" if any(line.strip() in {"OpenD", "FutuOpenD"}
                         for line in text.splitlines()) else "ABSENT"
    ) if query == "PASS" else "UNKNOWN"
    # Reproduce the failed installer import without creating an OpenD context,
    # touching subscriptions or sending a readiness notification. Only fixed
    # classifications cross the private-host boundary; never exception text.
    query, text = _command([
        "/opt/stock-razor-opend-client/venv/bin/python", "-c",
        LEGACY_IMPORT_PROBE_CODE,
    ])
    out["legacy_notify_import"] = text.strip() if query == "PASS" else query
    return sanitize_runtime_diagnostics(out)

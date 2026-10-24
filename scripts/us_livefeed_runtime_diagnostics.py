"""Read-only fixed-host evidence; raw command/journal text never leaves this module."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import time
import xml.etree.ElementTree as ET

UNIT = "stock-razor-us-livefeed.service"
PROC_ROOT = Path("/proc")
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
    "gateway_config": {"PARSED_STARTUP_CANDIDATE", "MISSING", "INVALID", "UNKNOWN"},
    "gateway_api_port": {"MATCH", "MISMATCH", "DEFAULT", "UNKNOWN"},
    "gateway_telnet_port": {"CONFLICT", "OTHER", "UNSET", "UNKNOWN"},
    "gateway_rsa": {"CONFIGURED", "NOT_CONFIGURED", "UNKNOWN"},
    "offline_home": {"PRESENT", "DEFAULTED"},
    "offline_stage": {"ENVIRONMENT", "IMPORT_SDK", "IMPORT_PROTOBUF", "BUILD_REQUEST", "COMPLETE"},
    "offline_pack_errno": {"ENOENT", "EACCES", "EPERM", "EROFS", "ENOSPC", "EMFILE", "ENFILE", "ENOMEM", "UNKNOWN"},
    "offline_init_pack": {"PASS", "PACK_REJECTED", "STRUCT_ERROR", "ENCODE_ERROR", "KEY_ERROR", "OVERFLOW_ERROR", "OS_ERROR", "RUNTIME_ERROR", "ASSERTION_ERROR", "GENERIC_EXCEPTION", "ATTRIBUTE_ERROR", "TYPE_ERROR", "VALUE_ERROR", "IMPORT_ERROR", "OTHER_ERROR", "TIMEOUT", "UNAVAILABLE", "TRUNCATED"},
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
    "HANDSHAKE_TIMEOUT": r"init connect fail.*(?:timeout|超时)",
    "HANDSHAKE_DISCONNECT": r"init connect fail.*(?:disconnect|断开|连接关闭)",
    "HANDSHAKE_ENCRYPTION": r"init connect fail.*(?:RSA|encrypt|decrypt|加密|解密|密钥)",
    "HANDSHAKE_VERSION": r"init connect fail.*(?:version|版本)",
    "HANDSHAKE_LOGIN": r"init connect fail.*(?:not.login|未登录|未登陆)",
    "HANDSHAKE_ATTRIBUTE": r"init connect fail.*has no attribute",
    "HANDSHAKE_SHA": r"init connect fail.*check sha error",
    "HANDSHAKE_CONTEXT": r"init connect fail.*Context status bad",
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


OFFLINE_INIT_PACK_CODE = """import contextlib,io,json,sys,errno,struct,os,pathlib
out={'offline_init_pack':'OTHER_ERROR', 'offline_stage':'ENVIRONMENT', 'python_version':'.'.join(map(str,sys.version_info[:3]))}
try:
    # SSM can omit HOME; the service already declares it. Resolve the invoking
    # user's home only inside this child, without exposing a path.
    out['offline_home']='PRESENT' if os.environ.get('HOME') else 'DEFAULTED'
    if not os.environ.get('HOME'):
        os.environ['HOME']=str(pathlib.Path.home())
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        out['offline_stage']='IMPORT_SDK'
        import futu as ft
        out['offline_stage']='IMPORT_PROTOBUF'
        import google.protobuf
        out['sdk_version']=getattr(ft,'__version__','UNKNOWN')
        out['protobuf_version']=google.protobuf.__version__
        from futu.quote.quote_query import InitConnect
        out['offline_stage']='BUILD_REQUEST'
        result=InitConnect.pack_req(
            client_ver=int(ft.SysConfig.get_client_ver()), client_id=str(ft.SysConfig.get_client_id()),
            recv_notify=True, is_encrypt=False, push_proto_fmt=ft.SysConfig.get_proto_fmt())
    out['offline_stage']='COMPLETE'
    out['offline_init_pack']='PASS' if result[0]==ft.RET_OK and isinstance(result[2],bytes) and result[2] else 'PACK_REJECTED'
except Exception as exc:
    kind=type(exc).__name__
    out['offline_init_pack']={
        'EncodeError':'ENCODE_ERROR','KeyError':'KEY_ERROR',
        'OverflowError':'OVERFLOW_ERROR','RuntimeError':'RUNTIME_ERROR',
        'AssertionError':'ASSERTION_ERROR','Exception':'GENERIC_EXCEPTION',
        'AttributeError':'ATTRIBUTE_ERROR','TypeError':'TYPE_ERROR','ValueError':'VALUE_ERROR',
        'ImportError':'IMPORT_ERROR','ModuleNotFoundError':'IMPORT_ERROR',
    }.get(kind,'STRUCT_ERROR' if isinstance(exc,struct.error) else 'OS_ERROR' if isinstance(exc,OSError) else 'OTHER_ERROR')
    if isinstance(exc,OSError):
        out['offline_pack_errno']=errno.errorcode.get(exc.errno,'UNKNOWN')
print(json.dumps(out,separators=(',',':')))
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
    for key in ("sdk_version", "protobuf_version", "python_version"):
        version = value.get(key)
        if isinstance(version, str) and re.fullmatch(r"[0-9]{1,5}(?:\.[0-9]{1,5}){1,3}", version):
            out[key] = version
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


def gateway_config_metadata(listener_text):
    """Read the endpoint owner's startup config privately; publish enums only.

    This is current on-disk startup configuration, not proof of loaded state.
    Passwords, argv, account data, config/key paths and keys never leave here.
    """
    pids = {pid for line in listener_text.splitlines()
            if len(parts := line.split()) >= 5 and parts[3].endswith(":11111")
            for pid in re.findall(r'\("(?:OpenD|FutuOpenD|moomoo_OpenD)",pid=([0-9]{1,10}),', line)}
    out = {"gateway_config": "UNKNOWN"}
    if len(pids) != 1:
        return out
    proc = PROC_ROOT / next(iter(pids))
    try:
        executable = (proc / "exe").resolve(strict=True)
        if executable.name not in {"OpenD", "FutuOpenD", "moomoo_OpenD"}:
            return out
        with (proc / "cmdline").open("rb") as handle:
            raw = handle.read(65537)
        if len(raw) > 65536:
            return out
        # Official OpenD command format is -key=value; command-line wins.
        args = raw.decode("utf-8").split("\x00")
        overrides = dict(arg[1:].split("=", 1) for arg in args
                         if arg.startswith(("-cfg_file=", "-api_port=")))
        default = "FutuOpenD.xml" if executable.name == "FutuOpenD" else "OpenD.xml"
        config_path = Path(overrides.get("cfg_file", str(executable.parent / default)))
        if not config_path.is_absolute():
            return out
        descriptor = os.open(config_path, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return {"gateway_config": "INVALID"}
            raw = handle.read(65537)
        if len(raw) > 65536 or b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
            return {"gateway_config": "INVALID"}
        root = ET.fromstring(raw)

        def value(name):
            nodes = root.findall(name)
            if len(nodes) > 1:
                raise ValueError("duplicate config field")
            return (nodes[0].text or "").strip() if nodes else ""
        api = overrides.get("api_port", value("api_port"))
        telnet = value("telnet_port")
        rsa = value("rsa_private_key")
        out = {"gateway_config": "PARSED_STARTUP_CANDIDATE",
               "gateway_api_port": "DEFAULT" if not api else "MATCH" if api == "11111" else "MISMATCH" if re.fullmatch(r"[0-9]{1,5}", api) and 0 < int(api) <= 65535 else "UNKNOWN",
               "gateway_telnet_port": "UNSET" if not telnet else "CONFLICT" if telnet == "11111" else "OTHER" if re.fullmatch(r"[0-9]{1,5}", telnet) and 0 < int(telnet) <= 65535 else "UNKNOWN",
               "gateway_rsa": "CONFIGURED" if rsa else "NOT_CONFIGURED"}
    except FileNotFoundError:
        out = {"gateway_config": "MISSING"}
    except (OSError, ValueError, ET.ParseError, RuntimeError):
        out = {"gateway_config": "INVALID"}
    return out


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
        out.update(gateway_config_metadata(text))
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
    # Serialization only: no context, socket, credentials, subscriptions or
    # protocol-config mutation. This does not prove server compatibility.
    query, text = _command([
        "/opt/stock-razor-opend-client/venv/bin/python", "-c", OFFLINE_INIT_PACK_CODE,
    ])
    out["offline_init_pack"] = query if query != "PASS" else "UNAVAILABLE"
    if query == "PASS":
        try:
            packed = json.loads(text)
        except (ValueError, TypeError, RecursionError):
            packed = None
        if isinstance(packed, dict):
            allowed = {key: packed[key] for key in (
                "offline_init_pack", "offline_pack_errno", "sdk_version", "protobuf_version", "python_version", "offline_home", "offline_stage"
            ) if key in packed}
            out.update(allowed)
    return sanitize_runtime_diagnostics(out)

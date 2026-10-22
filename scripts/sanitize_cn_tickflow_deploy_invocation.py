#!/usr/bin/env python3
"""Emit bounded, non-sensitive diagnostics for one SSM TickFlow deploy invocation."""
from __future__ import annotations

import json
import re
import sys
from typing import Any

SAFE_STATUS = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
SAFE_STAGE = re.compile(r"^[A-Z_]{1,40}$")
MARKER = re.compile(r"^CN_TICKFLOW_(INSTALL_FAILED_STAGE|ROLLBACK)=([A-Z_]{1,40})$")

def classify(stdout: str, stderr: str) -> str:
    text = (stdout + "\n" + stderr).lower()
    rules = (
        ("DISK_SPACE", ("no space left on device", "enospc")),
        ("NETWORK_DNS", ("temporary failure in name resolution", "could not resolve", "name or service not known")),
        ("NETWORK_TLS_OR_HTTP", ("curl: (", "http error", "ssl certificate problem")),
        ("GIT_FETCH", ("fatal: ", "couldn't find remote ref", "could not read from remote repository")),
        ("PYTHON_DEPENDENCY", ("pip._vendor", "error: could not", "no matching distribution found")),
        ("PERMISSION", ("permission denied", "operation not permitted")),
        ("SYSTEMD", ("failed to restart", "job for ", "failed with result")),
        ("VERIFIER", ("cn_tickflow_worker_verify=blocked", "assertionerror")),
        ("COMMAND_OR_PATH", ("command not found", "no such file or directory")),
    )
    for label, markers in rules:
        if any(marker in text for marker in markers):
            return label
    if re.search(r"^CN_TICKFLOW_INSTALL_FAILED_STAGE=[A-Z_]{1,40}$", stdout + "\n" + stderr, re.MULTILINE):
        return "INSTALLER_STAGE_FAILURE"
    if "cn_tickflow_rollback=attempted" in text:
        return "INSTALLER_UNKNOWN_STAGE"
    return "NONE" if not text.strip() else "UNKNOWN"

def project(payload: dict[str, Any]) -> list[str]:
    status = payload.get("Status")
    details = payload.get("StatusDetails")
    code = payload.get("ResponseCode")
    stdout = payload.get("StandardOutputContent")
    stderr = payload.get("StandardErrorContent")
    stdout = stdout if isinstance(stdout, str) else ""
    stderr = stderr if isinstance(stderr, str) else ""
    lines = [
        "CN_TICKFLOW_COMMAND_STATUS=" + (status if isinstance(status, str) and SAFE_STATUS.fullmatch(status) else "UNKNOWN"),
        "CN_TICKFLOW_COMMAND_STATUS_DETAILS=" + (details if isinstance(details, str) and SAFE_STATUS.fullmatch(details) else "UNKNOWN"),
        "CN_TICKFLOW_RESPONSE_CODE=" + (str(code) if type(code) is int and -1 <= code <= 255 else "UNKNOWN"),
        "CN_TICKFLOW_STDOUT_CHARS=" + str(min(len(stdout), 1000000)),
        "CN_TICKFLOW_STDERR_CHARS=" + str(min(len(stderr), 1000000)),
        "CN_TICKFLOW_FAILURE_CLASS=" + classify(stdout, stderr),
    ]
    found = set()
    for line in (stdout + "\n" + stderr).splitlines():
        match = MARKER.fullmatch(line.strip())
        if match:
            name, value = match.groups()
            if (name == "INSTALL_FAILED_STAGE" and SAFE_STAGE.fullmatch(value)) or (name == "ROLLBACK" and value in ("ATTEMPTED", "NOT_NEEDED")):
                found.add((name, value))
    for name, value in sorted(found):
        lines.append("CN_TICKFLOW_" + name + "=" + value)
    return lines

def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("CN_TICKFLOW_INVOCATION_JSON=INVALID")
        return 2
    if not isinstance(payload, dict):
        print("CN_TICKFLOW_INVOCATION_JSON=INVALID")
        return 2
    print("\n".join(project(payload)))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

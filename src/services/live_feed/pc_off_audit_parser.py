"""Parsing helpers for AWS SSM journal output used by PC-off audits."""

import json
import re
from collections.abc import Iterable

_HEARTBEAT = re.compile(r'(\{"type":"futures_runtime_heartbeat".*?\})(?=\\n|$)')


def extract_futures_heartbeat_payloads(lines: Iterable[str]) -> list[dict]:
    """Extract heartbeat JSON from plain journal lines or AWS CLI text-escaped output."""
    payloads = []
    for raw in lines:
        candidates = (raw, raw.replace(r'\"', '"'))
        for candidate in candidates:
            match = _HEARTBEAT.search(candidate)
            if not match:
                continue
            payload = json.loads(match.group(1))
            if payload.get("type") == "futures_runtime_heartbeat":
                payloads.append(payload)
            break
    return payloads

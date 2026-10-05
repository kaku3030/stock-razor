"""Parsing helpers for AWS SSM journal output used by PC-off audits."""

import json
from collections.abc import Iterable

_MARKER = '"type":"futures_runtime_heartbeat"'


def extract_futures_heartbeat_payloads(lines: Iterable[str]) -> list[dict]:
    """Extract heartbeat objects without depending on journal line boundaries."""
    text = "".join(lines)
    text = text.replace(chr(92) + '"', '"').replace(chr(92) + "n", "\n")
    decoder = json.JSONDecoder()
    payloads = []
    cursor = 0
    while True:
        marker = text.find(_MARKER, cursor)
        if marker < 0:
            break
        start = text.rfind("{", 0, marker)
        if start < 0:
            cursor = marker + len(_MARKER)
            continue
        try:
            payload, consumed = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            cursor = marker + len(_MARKER)
            continue
        if isinstance(payload, dict) and payload.get("type") == "futures_runtime_heartbeat":
            payloads.append(payload)
        cursor = start + consumed
    return payloads

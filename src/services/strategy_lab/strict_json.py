"""Strict JSON parsing for audit-critical research evidence.

This helper is intentionally small and semantics-free.  It rejects ambiguous
or non-standard JSON before domain schema/digest validation so different
consumers cannot silently choose different meanings for the same evidence
bytes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads_strict_json(raw: str | bytes, label: str = "JSON evidence") -> Any:
    """Parse UTF-8 JSON while rejecting duplicate keys and NaN/Infinity."""

    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{label} must be UTF-8") from exc
    elif isinstance(raw, str):
        text = raw
    else:
        raise TypeError("strict JSON input must be str or bytes")

    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc


def load_strict_json(path: str | Path, label: str = "JSON evidence") -> Any:
    return loads_strict_json(Path(path).read_bytes(), label)

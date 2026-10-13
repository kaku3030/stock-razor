#!/usr/bin/env python3
"""Project fixed SSM probe output into a small public-safe evidence summary."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping


SAFE_KEYS = {
    "schema", "probe", "status", "reason", "observed_at_utc", "emitted_at_utc",
    "sequence", "subscription", "push", "crosscheck", "delivery_mode",
    "bar_closure", "qot_right_notification", "us_qot_right", "opend_reachable",
    "query_status", "radar_admission", "source_arbiter_admission", "paper_auto_ready",
    "live_trade", "trade_execution", "mcp_protocol_endpoint", "mcp_initialize",
    "mcp_public_exposure", "aws_private_mcp_runtime", "direct_opend_overlap_match",
    "bar_advancement", "stale_tail_regression", "currentness_metadata", "entitlement",
    "generation", "runtime_git_worktree", "checkout_dirty", "content_provenance_match",
    "expected_source_manifest", "expected_source_manifest_sha256", "runtime_source_manifest_sha256",
}
SAFE_LINE_KEYS = {
    "RADAR_ADMISSION", "SOURCE_ARBITER_ADMISSION", "PAPER_AUTO_READY", "LIVE_TRADE",
    "TRADE_EXECUTION", "DELIVERY_MODE", "BAR_CLOSURE", "QOT_RIGHT_NOTIFICATION",
    "US_QOT_RIGHT", "SUBSCRIPTION", "PUSH", "CROSSCHECK", "CURRENTNESS_METADATA",
    "ENTITLEMENT", "GENERATION", "DIRECT_OPEND_OVERLAP_MATCH", "BAR_ADVANCEMENT",
    "STALE_TAIL_REGRESSION", "MCP_INITIALIZE", "MCP_PUBLIC_EXPOSURE", "AWS_PRIVATE_MCP_RUNTIME",
    "MCP_PROTOCOL_ENDPOINT", "RUNTIME_GIT_WORKTREE", "CHECKOUT_DIRTY", "CONTENT_PROVENANCE_MATCH",
    "EXPECTED_SOURCE_MANIFEST", "EXPECTED_SOURCE_MANIFEST_SHA256", "RUNTIME_SOURCE_MANIFEST_SHA256",
}


def _safe_json(value: Mapping[str, object]) -> dict[str, object]:
    result = {}
    for key in SAFE_KEYS:
        if key not in value:
            continue
        item = value[key]
        if isinstance(item, (str, int, float, bool)) and _safe_scalar(key, item) is not None:
            result[key] = item
    symbols = value.get("symbols")
    if isinstance(symbols, Mapping):
        result["symbol_count"] = len(symbols)
        timeframes: dict[str, dict[str, object]] = {}
        for item in symbols.values():
            if not isinstance(item, Mapping):
                continue
            frames = item.get("timeframes")
            if not isinstance(frames, Mapping):
                continue
            for timeframe, frame in frames.items():
                if not isinstance(frame, Mapping):
                    continue
                summary = timeframes.setdefault(str(timeframe), {"count": 0, "latest_end_utc": None})
                summary["count"] = max(int(summary["count"]), int(frame.get("count") or 0))
                latest = frame.get("latest_end_utc")
                if isinstance(latest, str) and latest > str(summary["latest_end_utc"] or ""):
                    summary["latest_end_utc"] = latest
        if timeframes:
            result["timeframes"] = timeframes
    return result


def _safe_scalar(key: str, value: object) -> object | None:
    if not isinstance(value, (str, int, float, bool)):
        return None
    if isinstance(value, str):
        lowered = value.lower()
        if len(value) > 120 or any(term in lowered for term in ("secret", "token", "password", "account", "bearer", "api_key")):
            return None
        if key.endswith("_utc") and not re.fullmatch(r"[0-9T:+.Z-]{1,40}", value):
            return None
        if key.endswith("_sha256") and not re.fullmatch(r"[a-f0-9]{64}|UNAVAILABLE", value):
            return None
    return value


def project(raw: str) -> list[str]:
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                value = json.loads(stripped)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                safe = _safe_json(value)
                if safe:
                    lines.append("SANITIZED_PROBE=" + json.dumps(safe, sort_keys=True, separators=(",", ":")))
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key in SAFE_LINE_KEYS and _safe_scalar(key, value) is not None:
            lines.append(key + "=" + value[:120])
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", required=True)
    args = parser.parse_args()
    del args
    result = project(sys.stdin.read())
    if result:
        print("SANITIZED_EVIDENCE=PASS")
        print("\n".join(result))
    else:
        print("SANITIZED_EVIDENCE=NOT_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

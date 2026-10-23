#!/usr/bin/env python3
"""Project fixed SSM probe output into a small public-safe evidence summary."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping

if __package__:
    from .us_livefeed_runtime_diagnostics import sanitize_runtime_diagnostics
else:
    from us_livefeed_runtime_diagnostics import sanitize_runtime_diagnostics


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
    "MCP_TOOL_SURFACE_MISMATCH", "PRIVATE_MCP_TOOL_DISCOVERY_8_OF_8",
    "MCP_PROTOCOL_TOOL_CALL_FAILED", "MCP_LIST_TOOLS", "MCP_CALL_SEQUENCE",
}


def _safe_json(value: Mapping[str, object]) -> dict[str, object]:
    result = {}
    for key in SAFE_KEYS:
        if key not in value:
            continue
        item = value[key]
        if isinstance(item, (str, int, float, bool)) and _safe_scalar(key, item) is not None:
            result[key] = item
    diagnostics = sanitize_runtime_diagnostics(value.get("runtime_diagnostics"))
    if diagnostics:
        result["runtime_diagnostics"] = diagnostics
    symbols = value.get("symbols")
    if isinstance(symbols, Mapping) and len(symbols) <= 500:
        result["symbol_count"] = len(symbols)
        timeframes: dict[str, dict[str, object]] = {}
        # Never forward provider-defined field names, arbitrary numbers or
        # unvalidated timestamps to PUBLIC GitHub Actions output.
        for item in symbols.values():
            if not isinstance(item, Mapping):
                continue
            frames = item.get("timeframes")
            if not isinstance(frames, Mapping):
                continue
            for timeframe, frame in frames.items():
                if timeframe not in ("D1", "1D", "1d", "1H", "60m", "15m", "5m", "1m") or not isinstance(frame, Mapping):
                    continue
                count = frame.get("count")
                if type(count) is not int or count < 0 or count > 4096:
                    continue
                summary = timeframes.setdefault(timeframe, {"count": 0, "latest_end_utc": None})
                summary["count"] = max(summary["count"], count)
                latest = frame.get("latest_end_utc")
                if _safe_scalar("latest_end_utc", latest) is not None and latest > str(summary["latest_end_utc"] or ""):
                    summary["latest_end_utc"] = latest
        if timeframes:
            result["timeframes"] = timeframes
    return result


def _safe_scalar(key: str, value: object) -> object | None:
    """Allow only bounded typed evidence, never arbitrary remote text."""
    if type(value) is bool:
        return value if key in ("paper_auto_ready", "live_trade", "trade_execution", "opend_reachable", "checkout_dirty") else None
    if type(value) is int:
        return value if key == "sequence" and 0 <= value <= 1_000_000 else None
    if not isinstance(value, str):
        return None
    if any(term in value.lower() for term in ("secret", "token", "password", "account", "bearer", "api_key", "credential")):
        return None
    if key.endswith("_utc"):
        return value if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:[.][0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", value) else None
    if key.endswith("_sha256"):
        return value if re.fullmatch(r"[a-f0-9]{64}|UNAVAILABLE", value) else None
    if key in ("schema", "probe"):
        return value if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", value) else None
    # All remaining fields are finite-style status tokens; URLs, hostnames,
    # exception strings, paths, raw symbols, arbitrary identifiers are denied.
    return value if re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value) else None


def project(raw: str) -> list[str]:
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                value = json.loads(stripped)
            except (TypeError, ValueError, RecursionError):
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
    parser.add_argument("--failed-status", action="store_true")
    args = parser.parse_args()
    result = project(sys.stdin.read())
    if result:
        print("SANITIZED_EVIDENCE=FAILED_COMMAND_ENUMS_ONLY" if args.failed_status
              else "SANITIZED_EVIDENCE=AVAILABLE_NOT_QUALIFIED")
        print("\n".join(result))
    else:
        print("SANITIZED_EVIDENCE=NOT_VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

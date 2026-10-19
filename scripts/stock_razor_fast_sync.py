#!/usr/bin/env python3
"""Fast project-only sync: route new discussion topics and validate owner-published events.

No remote calls or trade authority. Owner-authenticated Github issue comments are
the append-only project discussion feed; the existing Context Manager remains the
live read model. ChatGPT windows must actively call connected tools to read it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import unicodedata

SCHEMA = "stock_razor_fast_context_sync_v1"
PREFIX = "STOCK_RAZOR_SYNC_V1\n"
REPO = "kaku3030/stock-razor"
ISSUE = 924
MAX_SUMMARY = 480
TOPICS = ("us", "cn", "strategy", "engineering", "portfolio", "policy")
STATUSES = ("DECIDED", "IN_PROGRESS", "BLOCKED", "VERIFIED", "RESEARCH_ONLY")
SHA = re.compile(r"^[0-9a-f]{40}$")
EVIDENCE = re.compile(r"^https://github[.]com/kaku3030/stock-razor/(?:pull|issues|actions/runs)/[0-9]{1,20}(?:[#?][A-Za-z0-9._=/&-]{1,180})?$")
SAFE_SUMMARY = re.compile(r"^[^<>\x00-\x1f]{12,480}$")
TOKENS = {
    "us": ["opend", "美股", "美盘", "futu", "qqq", "nvda", "tsla", "amd", "nasdaq", "美股雷达"],
    "cn": ["tickflow", "a股", "a 股", "沪深", "中国股票", "电力etf", "a股雷达"],
    "strategy": ["策略", "回测", "复盘", "replay", "15m", "15分钟", "1h", "1小时", "日线", "d1", "oos", "多周期", "入场信号"],
    "engineering": ["stock razor", "stock-razor", "stockrazor", "雷达", "云端", "aws", "main control", "反馈站", "feedback hub", "自动交易", "自主工程", "新窗口", "跨窗口", "同步"],
    "portfolio": ["持仓", "建仓", "止损", "仓位", "nisa", "投资组合", "交易账户", "盈亏", "配仓"],
    "policy": ["政策", "美联储", "联储", "宏观", "fed", "利率", "油价", "黄金", "汇率"],
}


class FastSyncError(ValueError):
    pass


def norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def route_discussion(message: str, *, stock_razor_window: bool = False) -> dict:
    if not isinstance(message, str) or not 1 <= len(message) <= 2000:
        raise FastSyncError("ROUTE_INPUT_INVALID")
    query = norm(message)
    found = []
    for topic, words in TOKENS.items():
        if any(w in query for w in words):
            found.append(topic)
    # An existing dedicated project window retains topic when user says "继续".
    if stock_razor_window and not found:
        found = ["engineering"]
    return {
        "schema": SCHEMA, "action": "FETCH_CURRENT_MAIN_AND_CONTEXT"
        if found else "NO_PROJECT_TRIGGER",
        "topics": found,
        "priority": "FAST_FIRST_READ",
        "entrypoints": [
            "GITHUB_CURRENT_MAIN_SHA",
            "SAME_SHA_AGENTS_SKILL_REGISTRY_ASSOCIATIONS",
            "STOCK_RAZOR_MCP_CONTEXT_MANAGER_SENTINEL",
            "GITHUB_ISSUE_924_OWNER_SYNC_COMMENTS",
        ] if found else [],
        "no_access_state": "SYNC_NOT_VERIFIED",
        "max_expected_lag": "MEASURE_NOT_PROMISED",
    }


def _time(value: object) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("naive")
        now = datetime.now(timezone.utc)
        if (parsed - now).total_seconds() > 120:
            raise ValueError("future")
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError):
        raise FastSyncError("COMMENT_TIMESTAMP_INVALID") from None


def parse_comment(event: dict) -> dict:
    if not isinstance(event, dict) or (event.get("repository") or {}).get("full_name") != REPO:
        raise FastSyncError("REPO_NOT_AUTHORIZED")
    issue = event.get("issue") or {}
    if issue.get("number") != ISSUE:
        raise FastSyncError("ISSUE_NOT_AUTHORIZED")
    comment = event.get("comment") or {}
    user = comment.get("user") or {}
    if user.get("login") != "kaku3030" or comment.get("author_association") != "OWNER":
        raise FastSyncError("PUBLISHER_NOT_AUTHORIZED")
    cid = comment.get("id")
    if type(cid) is not int or cid < 1:
        raise FastSyncError("COMMENT_ID_INVALID")
    created_at = _time(comment.get("created_at"))
    body = comment.get("body")
    if not isinstance(body, str) or not body.startswith(PREFIX) or len(body) > 1900:
        raise FastSyncError("SYNC_ENVELOPE_INVALID")
    try:
        packet = json.loads(body[len(PREFIX):])
    except ValueError:
        raise FastSyncError("SYNC_JSON_INVALID") from None
    if not isinstance(packet, dict) or set(packet) != {
        "topic", "state", "summary", "evidence_url", "source_sha"
    }:
        raise FastSyncError("SYNC_FIELDS_INVALID")
    if packet["topic"] not in TOPICS or packet["state"] not in STATUSES:
        raise FastSyncError("SYNC_ENUM_INVALID")
    summary = packet["summary"]
    if not isinstance(summary, str) or not SAFE_SUMMARY.fullmatch(summary):
        raise FastSyncError("SYNC_SUMMARY_INVALID")
    # No credentials/private positions, no arbitrary raw log or code fragments.
    lowered = summary.lower()
    if any(s in lowered for s in ("api_key", "secret", "password", "token=", "bearer ", "-----begin", "账号密码")):
        raise FastSyncError("SYNC_SENSITIVE_TEXT_BLOCKED")
    evidence = packet["evidence_url"]
    if not isinstance(evidence, str) or not EVIDENCE.fullmatch(evidence):
        raise FastSyncError("SYNC_EVIDENCE_INVALID")
    sha = packet["source_sha"]
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise FastSyncError("SYNC_SHA_INVALID")
    topic = packet["topic"]
    event_type = "radar_sync" if topic in ("us", "cn", "strategy", "portfolio") else "priorities_sync"
    source = "radar" if event_type == "radar_sync" else "engineering"
    return {
        "schema": SCHEMA, "status": "ACCEPTED",
        "event_id": "github:sync:" + str(cid),
        "event_type": event_type, "source": source,
        "source_ref": "github/issue_comment/" + str(cid),
        "payload": {"topic": topic, "state": packet["state"],
                    "summary": summary, "evidence_url": evidence,
                    "source_sha": sha, "published_at_utc": created_at,
                    "comment_id": cid,
                    "qualification": "USER_DECISION_OR_ENGINEERING_UPDATE_NOT_LIVE_TRADE_SIGNAL"},
        "ttl_seconds": 259200,  # 3-day Context Manager projection; GitHub comment remains durable
        "sync_transport": "GITHUB_ISSUE_COMMENT_TO_AWS_CONTEXT_MANAGER",
        "delivery_receipt": "NOT_VERIFIED_UNTIL_SSM_READBACK",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--route")
    group.add_argument("--parse-comment", type=Path)
    parser.add_argument("--stock-razor-window", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.route is not None:
            data = route_discussion(args.route, stock_razor_window=args.stock_razor_window)
        else:
            path = args.parse_comment
            if not path.is_file() or not 0 < path.stat().st_size <= 20000:
                raise FastSyncError("EVENT_MISSING_OR_OVERSIZED")
            data = parse_comment(json.loads(path.read_text(encoding="utf-8")))
        print(json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 0
    except (FastSyncError, OSError, UnicodeError, ValueError, TypeError) as exc:
        message = str(exc) if isinstance(exc, FastSyncError) else "MALFORMED_EVENT"
        print(json.dumps({"status": "BLOCKED", "reason": message}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

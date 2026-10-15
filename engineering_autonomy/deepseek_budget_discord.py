"""DeepSeek budget reminders via an opt-in Discord webhook.

Only a categorical status from the official balance GET is sent; never raw
wallet amounts, DeepSeek credentials, response bodies or model conversation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request

from engineering_autonomy.deepseek_budget import read_status


def message_for_status(status: str) -> str | None:
    if status == "OK":
        return None
    if status == "TEST":
        return ("✅ STOCK RAZOR · Discord 通知通道测试成功。"
                "DeepSeek API 余额未触发低余额提醒，这是一条人工验收测试消息，无需充值。")
    if status == "LOW":
        return ("⚠️ STOCK RAZOR · DeepSeek API 余额较低（CNY ≤ 10 或 USD ≤ 2）。"
                "Engineering Autonomy 已阻止新的付费编码任务；请准备充值。")
    if status == "EMPTY":
        return ("🔴 STOCK RAZOR · DeepSeek API 余额已耗尽。"
                "Engineering Autonomy 已暂停付费编码，请登录 DeepSeek 官方开发者平台充值。")
    if status == "UNAVAILABLE":
        return ("🔴 STOCK RAZOR · DeepSeek API 官方报告余额不可用。"
                "已阻止付费编码；请检查账户、余额或充值。")
    if status == "UNKNOWN":
        return ("⚠️ STOCK RAZOR · 无法核实 DeepSeek API 余额（网络、鉴权或服务异常）。"
                "工程付费任务已阻断；这不代表余额为零。")
    raise ValueError("unknown budget status")


def send_discord(status: str, webhook: str, user_id: str = "", opener=None) -> str:
    message = message_for_status(status)
    if message is None:
        return "HEALTHY_NO_ALERT"
    if not webhook:
        return "CHANNEL_NOT_CONFIGURED"
    url = urllib.parse.urlsplit(webhook)
    if url.scheme != "https" or url.hostname not in {"discord.com", "discordapp.com"}:
        raise ValueError("unsupported webhook")
    if not re.fullmatch(r"/api(?:/v\d+)?/webhooks/\d{16,22}/[-_A-Za-z0-9]{20,}", url.path):
        raise ValueError("invalid webhook path")
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("unexpected webhook components")
    mention = ""
    allowed = {"parse": []}
    if user_id:
        if not re.fullmatch(r"\d{16,22}", user_id):
            raise ValueError("invalid mention id")
        mention = f"<@{user_id}> "
        allowed["users"] = [user_id]
    body = json.dumps(
        {"content": mention + message, "allowed_mentions": allowed},
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        webhook, data=body, headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = opener or urllib.request.urlopen
    with opener(request, timeout=12) as response:
        if response.status not in (200, 204):
            raise ValueError("Discord did not accept alert")
    return "ALERT_SENT"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-file", type=Path)
    parser.add_argument("--test-delivery", action="store_true",
                        help="send an explicitly labelled test message (manual only)")
    args = parser.parse_args()
    try:
        if not args.test_delivery and args.status_file is None:
            raise ValueError("missing status file")
        status = "TEST" if args.test_delivery else read_status(args.status_file)
        result = send_discord(
            status, os.getenv("DISCORD_WEBHOOK_URL", ""),
            os.getenv("STOCK_RAZOR_DISCORD_USER_ID", ""),
        )
    except (ValueError, TypeError, KeyError, OSError, urllib.error.URLError,
            TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
        print("BUDGET_ALERT=FAILED_CLOSED")
        return 2
    print("BUDGET_ALERT=" + result)
    return 0 if result in ("HEALTHY_NO_ALERT", "ALERT_SENT") else 2


if __name__ == "__main__":
    raise SystemExit(main())

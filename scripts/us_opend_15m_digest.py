#!/usr/bin/env python3
"""Read-only OpenD live watch with separate provisional and closed-bar research confirmation."""
from __future__ import annotations
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

FILES = (
    ("/run/stock-razor-us-livefeed/latest-heartbeat.json", 1000000),
    ("/run/stock-razor-us-livefeed/canonical-market-snapshot.json", 40000000),
    ("/run/stock-razor-us-radar/latest-research-state.json", 8000000),
)
SYMBOLS = ("US.QQQ", "US.NVDA", "US.TSLA", "US.AMD", "US.AAPL", "US.GLDM")
SCHEMA = "stock_razor_us_opend_15m_digest_v1"
SHA = re.compile(r"^[a-f0-9]{40}$")


def read(path, limit):
    try:
        file = Path(path)
        if not file.is_file() or not 0 < file.stat().st_size <= limit:
            return {}
        with file.open(encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, dict) else {}
    except (OSError, UnicodeError, ValueError):
        return {}


def utc(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except (ValueError, AttributeError, TypeError):
        return None


def validbar(series, now, max_age):
    if not isinstance(series, list) or not series or not isinstance(series[-1], dict):
        return ("UNKNOWN", "none")
    bar = series[-1]
    stamp = utc(bar.get("bar_end_utc"))
    if stamp is None:
        return ("UNKNOWN", "bad_stamp")
    age = (now - stamp).total_seconds()
    values = [bar.get(field) for field in ("open", "high", "low", "close", "volume")]
    finite = all(type(v) in (int, float) and math.isfinite(v) for v in values)
    if (not finite or values[2] > values[3] or values[3] > values[1]
            or values[0] < values[2] or values[0] > values[1] or values[4] < 0
            or age < -60 or age > max_age or not bar.get("is_closed")
            or not bar.get("is_complete") or bar.get("feed") != "opend"
            or bar.get("provider") != "futu"):
        return ("BLOCKED", "bad_or_stale")
    flags = {str(x).upper() for x in bar.get("quality_flags", [])}
    quality = "DEGRADED" if flags & {"VWAP_OUTSIDE_BAR_RANGE", "PARTIAL_TURNOVER", "STALE"} else "RESEARCH"
    return (quality, f"{stamp:%m-%d %H:%M}Z close={values[3]:.2f}")


def valid_watch_bar(series, now, max_age):
    """Qualify a current forming bar for observation without treating it as closed."""
    if not isinstance(series, list) or not series or not isinstance(series[-1], dict):
        return ("BLOCKED", "missing")
    bar = series[-1]
    stamp = utc(bar.get("bar_end_utc"))
    if stamp is None:
        return ("BLOCKED", "bad_stamp")
    age = (now - stamp).total_seconds()
    values = [bar.get(field) for field in ("open", "high", "low", "close", "volume")]
    finite = all(type(v) in (int, float) and math.isfinite(v) for v in values)
    if (not finite or values[2] > values[3] or values[3] > values[1]
            or values[0] < values[2] or values[0] > values[1] or values[4] < 0
            or age < -120 or age > max_age or bar.get("feed") != "opend"
            or bar.get("provider") != "futu"):
        return ("BLOCKED", "bad_or_stale")
    flags = {str(x).upper() for x in bar.get("quality_flags", [])}
    if flags & {"STALE", "INVALID_OHLCV", "OUT_OF_ORDER", "MISSING_BAR"}:
        return ("BLOCKED", "quality_flags")
    if not bar.get("is_closed") or not bar.get("is_complete"):
        return ("PROVISIONAL", f"{stamp:%H:%M:%S}Z forming close={values[3]:.2f}")
    if flags:
        return ("DEGRADED", f"{stamp:%H:%M:%S}Z close={values[3]:.2f}")
    return ("WATCH", f"{stamp:%H:%M:%S}Z close={values[3]:.2f}")


def render(health, market, radar, now):
    now = now.astimezone(timezone.utc)
    sha = market.get("repo_sha")
    evaluation = radar.get("evaluation")
    evaluation = evaluation if isinstance(evaluation, dict) else {}
    valid_source = (isinstance(sha, str) and bool(SHA.fullmatch(sha))
                    and health.get("repo_sha") == sha
                    and market.get("runtime_instance_id") == health.get("runtime_instance_id")
                    and radar.get("worker_repo_sha") == sha
                    and radar.get("expected_source_repo_sha") == sha
                    and market.get("radar_admission") == "BLOCKED"
                    and market.get("live_trade") is False and radar.get("live_trade") is False)
    stamp = utc(market.get("latest_source_timestamp_utc"))
    age = int((now - stamp).total_seconds()) if stamp else None
    source_fresh = age is not None and -60 <= age <= 1200
    gates = {
        "SOURCE_LINEAGE": valid_source,
        "SEQUENCE": evaluation.get("source_sequence") == market.get("sequence"),
        "FRESHNESS": source_fresh,
        "FINALITY": market.get("bar_closure") == health.get("bar_closure") == "PROVEN",
        "RADAR_POLL": radar.get("poll_status") == "PASS" and radar.get("radar_analysis_performed") is True,
    }
    states = {}
    for value in evaluation.get("symbols", []) if isinstance(evaluation.get("symbols"), list) else []:
        if isinstance(value, dict) and value.get("symbol") in SYMBOLS and value.get("status") == "RESEARCH_STATE":
            states[value["symbol"]] = value.get("technical_state") or {}
    rows = market.get("symbols")
    rows = rows if isinstance(rows, dict) else {}
    all_symbol_bars_healthy = True
    symbol_monitor = {}
    lines = [
        f"📡 STOCK RAZOR OpenD 实时盯盘 {now:%m-%d %H:%M} UTC",
        "数据完整性：" + ("PASS" if all(gates.values()) else "BLOCKED") +
        "｜盘中观察与收盘确认分开｜交易信号/下单：关闭",
        f"源数据时间：{stamp.isoformat() if stamp else 'UNKNOWN'}｜延迟：{age if age is not None else 'UNKNOWN'}s",
        "D1 / 1H / 15m 多周期研究状态；1m / 5m 盘中观察（未闭合只作候选）",
    ]
    for symbol in SYMBOLS:
        item = rows.get(symbol) or {}
        if not isinstance(item, dict) or item.get("feed") != "opend" or item.get("provider") != "futu":
            all_symbol_bars_healthy = False
            symbol_monitor[symbol] = {
                "watch_status": "BLOCKED", "candidate": "UNKNOWN",
                "research_confirmation": "PENDING_DATA", "reason": "OPEND_SYMBOL_MISSING",
            }
            lines.append(symbol[3:] + " OpenD缺失｜观察/确认均阻断")
            continue
        frames = item.get("timeframes") or {}
        q1m, detail1m = valid_watch_bar(frames.get("1m"), now, 120)
        q5m, detail5m = valid_watch_bar(frames.get("5m"), now, 420)
        q15, detail15 = validbar(frames.get("15m"), now, 1200)
        q1h, detail1h = validbar(frames.get("1h"), now, 5400)
        if q15 != "RESEARCH" or q1h != "RESEARCH":
            all_symbol_bars_healthy = False
        technical_state = states.get(symbol) or {}
        technical = technical_state.get("technical") or {}
        d1 = technical.get("daily") or {}
        day_text = (d1.get("quality") or {}).get("as_of")
        day = None
        if isinstance(day_text, str):
            try:
                day = datetime.fromisoformat(day_text[:10]).date()
            except ValueError:
                pass
        d1trend = d1.get("trend", "UNKNOWN") if day and 0 <= (now.date()-day).days <= 5 else "UNKNOWN"
        htrend = (technical.get("hourly") or {}).get("trend", "UNKNOWN") if q1h == "RESEARCH" else "UNKNOWN"
        mtrend = (technical.get("intraday") or {}).get("trend", "UNKNOWN") if q15 == "RESEARCH" else "UNKNOWN"
        alignment = str(technical_state.get("alignment", "unknown")).lower()
        watch_ok = (valid_source and source_fresh and q1m in {"WATCH", "PROVISIONAL", "DEGRADED"}
                    and q5m in {"WATCH", "PROVISIONAL", "DEGRADED"})
        candidate = {
            "aligned_bullish": "BULLISH_WATCH",
            "aligned_bearish": "BEARISH_WATCH",
            "aligned_neutral": "NEUTRAL_WATCH",
        }.get(alignment, "NO_QUALIFIED_SETUP")
        research_confirmed = (
            watch_ok and gates["SEQUENCE"] and gates["RADAR_POLL"] and gates["FINALITY"]
            and q15 == "RESEARCH" and q1h == "RESEARCH"
            and d1trend != "UNKNOWN" and alignment in {
                "aligned_bullish", "aligned_bearish", "aligned_neutral"
            }
        )
        confirmation = "CONFIRMED_MTF_RESEARCH" if research_confirmed else "PROVISIONAL_OR_WAITING"
        conditions = technical_state.get("watch_conditions")
        conditions = [str(value)[:140] for value in conditions[:3]] if isinstance(conditions, list) else []
        symbol_monitor[symbol] = {
            "watch_status": "ACTIVE" if watch_ok else "BLOCKED",
            "1m_state": q1m, "5m_state": q5m,
            "candidate": candidate if watch_ok else "UNKNOWN",
            "research_confirmation": confirmation,
            "alignment": alignment,
            "watch_conditions": conditions,
            "confirmation_requires_closed_bars": True,
        }
        if not watch_ok:
            all_symbol_bars_healthy = False
        lines.append(
            f"{symbol[3:]} D1:{d1trend} 1H:{htrend} 15m:{mtrend}"
            f"｜1m:{q1m} 5m:{q5m}｜观察:{candidate if watch_ok else 'BLOCKED'}"
            f"｜多周期:{confirmation}"
        )
        if conditions:
            lines.append("  条件：" + "；".join(conditions))
        if q15 != "RESEARCH" or q1h != "RESEARCH":
            lines.append(f"  等待闭合/质量复核：15m={q15}({detail15}) 1h={q1h}({detail1h})")
    gates["SYMBOL_BAR_QUALITY"] = all_symbol_bars_healthy
    if not all(gates.values()):
        lines.append("完整确认阻断：" + ",".join(name for name, passed in gates.items() if not passed))
    lines.append(
        "盘中形成K线用于候选观察；闭合后才复核多周期研究状态。"
        "这不是入场/出场指令；RADAR_ADMISSION=BLOCKED；LIVE_TRADE=NO。"
    )
    message = "\n".join(lines)
    if len(message) > 1900:
        message = message[:1870] + "\n[RESEARCH REPORT TRUNCATED]"
    active_count = sum(value["watch_status"] == "ACTIVE" for value in symbol_monitor.values())
    confirmed_count = sum(
        value["research_confirmation"] == "CONFIRMED_MTF_RESEARCH"
        for value in symbol_monitor.values()
    )
    return {
        "schema": SCHEMA,
        "status": "RESEARCH_ONLY" if all(gates.values()) else "BLOCKED",
        "monitor_status": "ACTIVE" if active_count else "BLOCKED",
        "active_watch_count": active_count,
        "research_alignment_confirmation_count": confirmed_count,
        "symbol_monitor": symbol_monitor,
        "message": message,
        "research_only": True,
        "can_confirm_research_alignment": bool(confirmed_count),
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


if __name__ == "__main__":
    print(json.dumps(render(*(read(*entry) for entry in FILES), datetime.now(timezone.utc)),
                     ensure_ascii=False, allow_nan=False, separators=(",", ":")))

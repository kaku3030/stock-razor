#!/usr/bin/env python3
"""A bounded read-only OpenD cloud cache + Radar D1/1H/15m digest, never a trade signal."""
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
    gates = {
        "SOURCE_LINEAGE": valid_source,
        "SEQUENCE": evaluation.get("source_sequence") == market.get("sequence"),
        "FRESHNESS": age is not None and -60 <= age <= 1200,
        "FINALITY": market.get("bar_closure") == health.get("bar_closure") == "PROVEN",
        "RADAR_POLL": radar.get("poll_status") == "PASS" and radar.get("radar_analysis_performed") is True,
    }
    states = {}
    for value in evaluation.get("symbols", []) if isinstance(evaluation.get("symbols"), list) else []:
        if isinstance(value, dict) and value.get("symbol") in SYMBOLS and value.get("status") == "RESEARCH_STATE":
            states[value["symbol"]] = value.get("technical_state") or {}
    rows = market.get("symbols")
    rows = rows if isinstance(rows, dict) else {}
    # A healthy global heartbeat cannot qualify an absent, provisional or degraded symbol.
    all_symbol_bars_healthy = True
    lines = [
        f"📡 STOCK RAZOR OpenD 云端15分钟研究快报 {now:%m-%d %H:%M} UTC",
        "行情资格：" + ("RESEARCH_ONLY" if all(gates.values()) else "BLOCKED") + "｜确认交易信号：无",
        f"实际K线源时间：{stamp.isoformat() if stamp else 'UNKNOWN'}｜延迟：{age if age is not None else 'UNKNOWN'}s",
        "D1趋势 / 1H趋势 / 15m趋势（仅研究，不构成下单信号）"
    ]
    for symbol in SYMBOLS:
        item = rows.get(symbol) or {}
        if not isinstance(item, dict) or item.get("feed") != "opend" or item.get("provider") != "futu":
            all_symbol_bars_healthy = False
            lines.append(symbol[3:] + " OpenD缺失")
            continue
        frames = item.get("timeframes") or {}
        q15, detail = validbar(frames.get("15m"), now, 1200)
        q1h, _ = validbar(frames.get("1h"), now, 5400)
        if q15 != "RESEARCH" or q1h != "RESEARCH":
            all_symbol_bars_healthy = False
        technical = (states.get(symbol) or {}).get("technical") or {}
        d1 = technical.get("daily") or {}
        # D1 quality.as_of is often an NYSE session DATE without a timezone.
        # Treat the calendar date only as historical research context, never finality proof.
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
        lines.append(f"{symbol[3:]} D1:{d1trend} 1H:{htrend} 15m:{mtrend} | {detail} ({q15})")
    gates["SYMBOL_BAR_QUALITY"] = all_symbol_bars_healthy
    lines[1] = "行情资格：" + ("RESEARCH_ONLY" if all(gates.values()) else "BLOCKED") + "｜确认交易信号：无"
    if not all(gates.values()):
        lines.append("阻断：" + ",".join(name for name, passed in gates.items() if not passed))
    lines.append("OpenD缓存只读；交易/自动下单关闭；D1如缺失则UNKNOWN。")
    message = "\n".join(lines)
    if len(message) > 1900:
        message = message[:1870] + "\n[RESEARCH REPORT TRUNCATED]"
    return {"schema": SCHEMA, "status": "RESEARCH_ONLY" if all(gates.values()) else "BLOCKED",
            "message": message, "research_only": True, "can_confirm_signal": False,
            "radar_admission": "BLOCKED", "live_trade": False}


if __name__ == "__main__":
    print(json.dumps(render(*(read(*entry) for entry in FILES), datetime.now(timezone.utc)),
                     ensure_ascii=False, allow_nan=False, separators=(",", ":")))

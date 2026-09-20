import copy
from datetime import datetime, timedelta, date, time, timezone
import hashlib
import json
import math
import os
import re
import tempfile
from src.technical.price_structure import (
    clean_json_value,
    _dedupe_bars_by_time,
    _structure_swings,
    _cluster_levels,
    _zone_strength,
    _nearest_zone,
    _structure_timeframe,
    build_price_structure_state,
)

from anthropic import Anthropic, APIConnectionError, APIStatusError, APITimeoutError
from openai import (
    OpenAI,
    APIConnectionError as OpenAIAPIConnectionError,
    APIStatusError as OpenAIAPIStatusError,
    APITimeoutError as OpenAIAPITimeoutError,
)
from mcp.server.fastmcp import FastMCP
from futu import (
    OpenQuoteContext,
    OpenSecTradeContext,
    TrdMarket,
    TrdEnv,
    SecurityFirm,
    RET_OK,
    SubType,
    KLType,
    Market,
)


def load_windows_user_env(name):
    """Load a Windows user-level environment variable if not inherited."""
    if name in os.environ:
        return

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Environment",
        ) as key:
            value, _ = winreg.QueryValueEx(key, name)

        if isinstance(value, str) and value.strip():
            os.environ[name] = value.strip()

    except (ImportError, FileNotFoundError, OSError):
        pass


load_windows_user_env("ANTHROPIC_API_KEY")
load_windows_user_env("DEEPSEEK_API_KEY")


mcp = FastMCP("stock-razor-realtime-monitor")

HOST = os.environ.get("STOCK_RAZOR_MOOMOO_HOST", "127.0.0.1")
PORT = int(os.environ.get("STOCK_RAZOR_MOOMOO_PORT", "11111"))
PRIMARY_US_ACCOUNT_ID = os.environ.get("STOCK_RAZOR_PRIMARY_US_ACCOUNT_ID")
RUNTIME_STATE_SCHEMA_VERSION = 1
EVENT_COOLDOWN_MINUTES = {
    "HIGH": 15,
    "MEDIUM": 30,
    "LOW": 60,
}
MAX_RECENT_FINGERPRINTS = 100
RUNTIME_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "runtime",
    "runtime_state.json",
)


def get_us_trade_ctx():
    return OpenSecTradeContext(
        filter_trdmarket=TrdMarket.US,
        host=HOST,
        port=PORT,
        security_firm=SecurityFirm.FUTUJP,
    )


def require_primary_us_account_id():
    """Return the configured account id without committing account data."""
    if not PRIMARY_US_ACCOUNT_ID:
        raise RuntimeError("STOCK_RAZOR_PRIMARY_US_ACCOUNT_ID is required")
    return PRIMARY_US_ACCOUNT_ID


def get_quote_ctx():
    return OpenQuoteContext(host=HOST, port=PORT)




def calculate_indicators_from_bars(bars):
    """Calculate indicators from oldest-to-newest OHLCV bars, without I/O.

    EMA uses the first close as its seed; MACD histogram is MACD - signal.
    RSI14 uses Wilder smoothing (flat prices return 50). Insufficient periods
    return None. Volume averages include the latest bar; missing volume is
    unknown, not zero. Input order is preserved and must be chronological.
    """
    if not bars or len(bars) < 2:
        return {"ok": False, "error": "not_enough_bars"}

    closes = []
    volumes = []
    for row in bars:
        try:
            close = float(row.get("close"))
            raw_volume = row.get("volume")
            volume = float(raw_volume) if raw_volume is not None else None
        except (TypeError, ValueError, OverflowError, AttributeError):
            return {"ok": False, "error": "invalid_bar_data"}
        if not math.isfinite(close):
            return {"ok": False, "error": "invalid_close_data"}
        if volume is not None and (not math.isfinite(volume) or volume < 0):
            return {"ok": False, "error": "invalid_volume_data"}
        closes.append(close)
        volumes.append(volume)

    def sma(values, period):
        if len(values) < period or any(v is None for v in values[-period:]):
            return None
        return sum(values[-period:]) / period

    def ema_series(values, period):
        alpha = 2 / (period + 1)
        result = [values[0]]
        for value in values[1:]:
            result.append(alpha * value + (1 - alpha) * result[-1])
        return result

    ma = {f"ma{period}": sma(closes, period) for period in (5, 10, 20, 60)}
    macd = {"macd": None, "signal": None, "histogram": None}
    if len(closes) >= 26:
        line = [a - b for a, b in zip(ema_series(closes, 12), ema_series(closes, 26))]
        macd["macd"] = line[-1]
        if len(closes) >= 34:
            macd["signal"] = ema_series(line, 9)[-1]
            macd["histogram"] = macd["macd"] - macd["signal"]

    rsi14 = None
    if len(closes) >= 15:
        changes = [b - a for a, b in zip(closes, closes[1:])]
        gain = sum(max(change, 0) for change in changes[:14]) / 14
        loss = sum(max(-change, 0) for change in changes[:14]) / 14
        for change in changes[14:]:
            gain = (gain * 13 + max(change, 0)) / 14
            loss = (loss * 13 + max(-change, 0)) / 14
        rsi14 = 50.0 if gain == loss == 0 else (
            100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)
        )

    volume_ma20 = sma(volumes, 20)
    return clean_json_value({
        "ok": True,
        "bar_count": len(bars),
        "latest_close": closes[-1],
        "ma": ma,
        "macd": macd,
        "rsi14": rsi14,
        "volume": {
            "latest": volumes[-1],
            "ma5": sma(volumes, 5),
            "ma20": volume_ma20,
            "ratio_to_ma20": (
                volumes[-1] / volume_ma20
                if volumes[-1] is not None and volume_ma20 not in (None, 0)
                else None
            ),
        },
    })


def summarize_timeframe_state(indicators):
    """Pure structural summary v1; no trading actions.

    Four votes: close/MA20, MA5/MA20, MACD/signal, RSI (>55 / <45).
    Net score >=3 / <=-3 is directional; otherwise neutral. MACD histogram
    must agree with MACD minus signal and is not counted twice. Required
    missing/invalid data is indeterminate. MA60 and volume never vote.
    """
    evidence = {}
    flags = []
    if not isinstance(indicators, dict) or indicators.get("ok") is not True:
        return {"state": "INDETERMINATE", "evidence": evidence,
                "flags": ["INDICATORS_UNAVAILABLE"]}

    def number(value):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value))

    ma = indicators.get("ma") or {}
    macd = indicators.get("macd") or {}
    volume = indicators.get("volume") or {}
    required = {
        "latest_close": indicators.get("latest_close"),
        "ma5": ma.get("ma5"), "ma20": ma.get("ma20"),
        "macd": macd.get("macd"), "signal": macd.get("signal"),
        "histogram": macd.get("histogram"), "rsi14": indicators.get("rsi14"),
    }
    invalid = [key for key, value in required.items() if not number(value)]
    evidence["inputs"] = {key: value if number(value) else None
                          for key, value in required.items()}
    if invalid:
        return {"state": "INDETERMINATE", "evidence": evidence,
                "flags": ["MISSING_OR_INVALID_" + key.upper() for key in invalid]}

    def sign(value):
        return 1 if value > 0 else -1 if value < 0 else 0

    price, ma5, ma20 = required["latest_close"], required["ma5"], required["ma20"]
    rsi = required["rsi14"]
    difference = required["macd"] - required["signal"]
    histogram = required["histogram"]
    if not 0 <= rsi <= 100:
        flags.append("INVALID_RSI_RANGE")
    if (sign(difference) != sign(histogram)
            or not math.isclose(difference, histogram, rel_tol=1e-9, abs_tol=1e-12)):
        flags.append("INCONSISTENT_MACD")
    if flags:
        return {"state": "INDETERMINATE", "evidence": evidence, "flags": flags}

    votes = {
        "price_vs_ma20": sign(price - ma20),
        "ma5_vs_ma20": sign(ma5 - ma20),
        "macd_direction": sign(difference),
        "rsi_direction": 1 if rsi > 55 else -1 if rsi < 45 else 0,
    }
    score = sum(votes.values())
    state = "BULLISH" if score >= 3 else "BEARISH" if score <= -3 else "NEUTRAL"
    evidence["votes"] = votes
    evidence["score"] = score
    ma60 = ma.get("ma60")
    evidence["price_vs_ma60"] = sign(price - ma60) if number(ma60) else None
    if not number(ma60):
        flags.append("MA60_UNAVAILABLE")
    ratio = volume.get("ratio_to_ma20")
    ratio = ratio if number(ratio) and ratio >= 0 else None
    evidence["volume_ratio"] = ratio
    evidence["volume_confirmation"] = (
        "UNAVAILABLE" if ratio is None else
        "NOT_APPLICABLE" if state == "NEUTRAL" else
        "CONFIRMED" if ratio >= 1 else "UNCONFIRMED"
    )
    if ratio is None:
        flags.append("VOLUME_RATIO_UNAVAILABLE")
    if rsi >= 70:
        flags.append("RSI_HIGH")
    elif rsi <= 30:
        flags.append("RSI_LOW")
    return {"state": state, "evidence": evidence, "flags": flags}


def summarize_timeframe_alignment(timeframe_states):
    """Require all three known timeframes for a determinate alignment."""
    states = [timeframe_states.get(key, {}).get("state")
              for key in ("daily", "hourly", "15m")]
    if any(state not in ("BULLISH", "BEARISH", "NEUTRAL") for state in states):
        return "INDETERMINATE"
    if all(state == "BULLISH" for state in states):
        return "ALIGNED_BULLISH"
    if all(state == "BEARISH" for state in states):
        return "ALIGNED_BEARISH"
    return "MIXED"


def compare_analysis_states(previous_state, current_state):
    """Compare two Analysis State snapshots and return deterministic events.

    This pure function does not persist snapshots, perform I/O, call an AI,
    notify users, or create trading instructions. New and removed symbols are
    outside Trigger Engine v0.1 and are not treated as state changes.
    """
    severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    timeframe_values = {"BULLISH", "NEUTRAL", "BEARISH", "INDETERMINATE"}
    overall_values = {
        "ALIGNED_BULLISH", "ALIGNED_BEARISH", "MIXED", "INDETERMINATE",
    }

    def empty_result(**extra):
        return {
            "ok": True,
            "triggered": False,
            **extra,
            "event_count": 0,
            "highest_severity": None,
            "events": [],
        }

    def invalid_result(error):
        return {
            "ok": False,
            "triggered": False,
            "event_count": 0,
            "highest_severity": None,
            "events": [],
            "error": error,
        }

    def validate_snapshot(snapshot):
        if not isinstance(snapshot, dict) or snapshot.get("ok") is not True:
            return False
        if not isinstance(snapshot.get("snapshot_time"), str):
            return False
        analysis_state = snapshot.get("analysis_state")
        if not isinstance(analysis_state, dict):
            return False
        for symbol, item in analysis_state.items():
            if not isinstance(symbol, str) or not isinstance(item, dict):
                return False
            health = item.get("data_health")
            timeframe = item.get("timeframe_state")
            if (not isinstance(health, dict)
                    or not isinstance(health.get("status"), str)
                    or not isinstance(timeframe, dict)
                    or timeframe.get("overall") not in overall_values):
                return False
            for key in ("daily", "hourly", "15m"):
                value = timeframe.get(key)
                if (not isinstance(value, dict)
                        or value.get("state") not in timeframe_values):
                    return False
        return True

    if previous_state is None:
        if not validate_snapshot(current_state):
            return invalid_result("invalid_current_state")
        return empty_result(baseline_created=True)
    if not validate_snapshot(previous_state):
        return invalid_result("invalid_previous_state")
    if not validate_snapshot(current_state):
        return invalid_result("invalid_current_state")

    timestamp = current_state["snapshot_time"]
    previous_items = previous_state["analysis_state"]
    current_items = current_state["analysis_state"]
    events = []

    def add_event(symbol, event_type, severity, previous, current, reason):
        events.append({
            "symbol": symbol,
            "event_type": event_type,
            "severity": severity,
            "previous": previous,
            "current": current,
            "reason": reason,
            "timestamp": timestamp,
        })

    for symbol in sorted(previous_items.keys() & current_items.keys()):
        previous_item = previous_items[symbol]
        current_item = current_items[symbol]
        previous_timeframe = previous_item["timeframe_state"]
        current_timeframe = current_item["timeframe_state"]

        previous_health = previous_item["data_health"]["status"]
        current_health = current_item["data_health"]["status"]
        if (previous_health == "OK") != (current_health == "OK"):
            severity = "HIGH" if previous_health == "OK" else "LOW"
            add_event(
                symbol, "DATA_HEALTH_CHANGED", severity,
                previous_health, current_health,
                f"Data health changed from {previous_health} to {current_health}.",
            )

        previous_overall = previous_timeframe["overall"]
        current_overall = current_timeframe["overall"]
        overall_changed = previous_overall != current_overall
        if overall_changed:
            aligned_flip = {
                previous_overall, current_overall,
            } == {"ALIGNED_BULLISH", "ALIGNED_BEARISH"}
            add_event(
                symbol, "OVERALL_STATE_CHANGED",
                "HIGH" if aligned_flip else "MEDIUM",
                previous_overall, current_overall,
                f"Overall state changed from {previous_overall} to {current_overall}.",
            )

        previous_daily = previous_timeframe["daily"]["state"]
        current_daily = current_timeframe["daily"]["state"]
        if previous_daily != current_daily:
            directional_flip = {
                previous_daily, current_daily,
            } == {"BULLISH", "BEARISH"}
            add_event(
                symbol, "DAILY_STATE_CHANGED",
                "HIGH" if directional_flip else "MEDIUM",
                previous_daily, current_daily,
                f"Daily state changed from {previous_daily} to {current_daily}.",
            )

        previous_hourly = previous_timeframe["hourly"]["state"]
        current_hourly = current_timeframe["hourly"]["state"]
        hourly_changed = previous_hourly != current_hourly
        if hourly_changed:
            directional_flip = {
                previous_hourly, current_hourly,
            } == {"BULLISH", "BEARISH"}
            add_event(
                symbol, "HOURLY_STATE_CHANGED",
                "MEDIUM" if directional_flip else "LOW",
                previous_hourly, current_hourly,
                f"Hourly state changed from {previous_hourly} to {current_hourly}.",
            )

        previous_15m = previous_timeframe["15m"]["state"]
        current_15m = current_timeframe["15m"]["state"]
        direct_15m_flip = {
            previous_15m, current_15m,
        } == {"BULLISH", "BEARISH"}
        confirmed_neutral_break = (
            previous_15m == "NEUTRAL"
            and current_15m in ("BULLISH", "BEARISH")
            and (hourly_changed or overall_changed)
        )
        if direct_15m_flip or confirmed_neutral_break:
            reason = (
                f"15m state changed from {previous_15m} to {current_15m}; "
                + ("direction reversed."
                   if direct_15m_flip
                   else "hourly or overall state changed at the same time.")
            )
            add_event(
                symbol, "SIGNIFICANT_15M_STATE_CHANGED", "MEDIUM",
                previous_15m, current_15m, reason,
            )

    highest_severity = (
        max((event["severity"] for event in events),
            key=severity_rank.get, default=None)
    )
    return {
        "ok": True,
        "triggered": bool(events),
        "event_count": len(events),
        "highest_severity": highest_severity,
        "events": events,
    }


def build_event_fingerprint(event):
    """Return a stable event identity that deliberately excludes timestamp."""
    if not isinstance(event, dict):
        return None
    parts = [event.get(key) for key in ("symbol", "event_type", "previous", "current")]
    if any(not isinstance(part, str) for part in parts):
        return None
    return "|".join(parts)


def _parse_event_runtime_time(value):
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_valid_event_runtime(event_runtime):
    if not isinstance(event_runtime, dict):
        return False
    for symbol, item in event_runtime.items():
        if (not isinstance(symbol, str)
                or not isinstance(item, dict)
                or _parse_event_runtime_time(item.get("last_actionable_at")) is None
                or item.get("last_severity") not in EVENT_COOLDOWN_MINUTES):
            return False
        fingerprints = item.get("recent_fingerprints")
        if not isinstance(fingerprints, dict) or len(fingerprints) > MAX_RECENT_FINGERPRINTS:
            return False
        if any(not isinstance(fingerprint, str)
               or _parse_event_runtime_time(timestamp) is None
               for fingerprint, timestamp in fingerprints.items()):
            return False
    return True


def apply_event_suppression(events, event_runtime, now=None):
    """Apply per-symbol dedup and cooldown rules without mutating inputs."""
    severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    if not isinstance(events, list):
        return {"ok": False, "status": "INVALID_EVENTS"}
    if not _is_valid_event_runtime(event_runtime):
        return {"ok": False, "status": "INVALID_EVENT_RUNTIME"}
    now_value = datetime.now() if now is None else _parse_event_runtime_time(now)
    if now_value is None:
        return {"ok": False, "status": "INVALID_NOW"}
    now_text = now_value.isoformat()

    copied_runtime = {
        symbol: {
            "last_actionable_at": item["last_actionable_at"],
            "last_severity": item["last_severity"],
            "recent_fingerprints": dict(item["recent_fingerprints"]),
        }
        for symbol, item in event_runtime.items()
    }
    raw_events = []
    actionable_events = []
    suppressed_events = []
    fingerprints_this_run = set()

    for event in events:
        fingerprint = build_event_fingerprint(event)
        severity = event.get("severity") if isinstance(event, dict) else None
        if fingerprint is None or severity not in EVENT_COOLDOWN_MINUTES:
            return {"ok": False, "status": "INVALID_EVENT"}
        raw_event = clean_json_value(dict(event))
        try:
            json.dumps(raw_event, allow_nan=False)
        except (TypeError, ValueError):
            return {"ok": False, "status": "INVALID_EVENT"}
        raw_events.append(raw_event)

        symbol = event["symbol"]
        previous_runtime = event_runtime.get(symbol)
        suppression_reason = None
        if fingerprint in fingerprints_this_run:
            suppression_reason = "DUPLICATE_EVENT"
        elif previous_runtime is not None:
            fingerprint_time = previous_runtime["recent_fingerprints"].get(fingerprint)
            try:
                fingerprint_age = (
                    (now_value - _parse_event_runtime_time(fingerprint_time)).total_seconds() / 60
                    if fingerprint_time is not None else None
                )
                last_age = (
                    now_value
                    - _parse_event_runtime_time(previous_runtime["last_actionable_at"])
                ).total_seconds() / 60
            except TypeError:
                return {"ok": False, "status": "INVALID_TIME_COMPARISON"}
            if (fingerprint_age is not None
                    and fingerprint_age < EVENT_COOLDOWN_MINUTES[severity]):
                suppression_reason = "DUPLICATE_EVENT"
            elif (last_age < EVENT_COOLDOWN_MINUTES[previous_runtime["last_severity"]]
                  and severity_rank[severity] <= severity_rank[previous_runtime["last_severity"]]):
                suppression_reason = "COOLDOWN_ACTIVE"

        if suppression_reason is None:
            actionable_events.append(raw_event)
            fingerprints_this_run.add(fingerprint)
        else:
            suppressed_events.append({
                **raw_event,
                "suppression_reason": suppression_reason,
            })

    actionable_by_symbol = {}
    for event in actionable_events:
        actionable_by_symbol.setdefault(event["symbol"], []).append(event)
    for symbol, symbol_events in actionable_by_symbol.items():
        item = copied_runtime.get(symbol, {
            "last_actionable_at": now_text,
            "last_severity": "LOW",
            "recent_fingerprints": {},
        })
        fingerprints = dict(item["recent_fingerprints"])
        for event in symbol_events:
            fingerprint = build_event_fingerprint(event)
            fingerprints.pop(fingerprint, None)
            fingerprints[fingerprint] = now_text
        ordered_fingerprints = sorted(
            fingerprints.items(),
            key=lambda pair: (_parse_event_runtime_time(pair[1]), pair[0]),
        )[-MAX_RECENT_FINGERPRINTS:]
        copied_runtime[symbol] = {
            "last_actionable_at": now_text,
            "last_severity": max(
                (event["severity"] for event in symbol_events),
                key=severity_rank.get,
            ),
            "recent_fingerprints": dict(ordered_fingerprints),
        }

    highest_actionable = max(
        (event["severity"] for event in actionable_events),
        key=severity_rank.get,
        default=None,
    )
    return {
        "ok": True,
        "raw_event_count": len(raw_events),
        "actionable_event_count": len(actionable_events),
        "suppressed_event_count": len(suppressed_events),
        "highest_actionable_severity": highest_actionable,
        "raw_events": raw_events,
        "actionable_events": actionable_events,
        "suppressed_events": suppressed_events,
        "event_runtime": copied_runtime,
    }


def build_trigger_snapshot(analysis_state):
    """Build the compact snapshot consumed by Runtime State Store v0.1."""
    if not isinstance(analysis_state, dict):
        return {"ok": False, "status": "INVALID_ANALYSIS_STATE"}
    snapshot_time = analysis_state.get("snapshot_time")
    account_alias = analysis_state.get("account_alias")
    items = analysis_state.get("analysis_state")
    if (not isinstance(snapshot_time, str)
            or not isinstance(account_alias, str)
            or not isinstance(items, dict)):
        return {"ok": False, "status": "INVALID_ANALYSIS_STATE"}

    symbols = {}
    allowed_states = {"BULLISH", "NEUTRAL", "BEARISH", "INDETERMINATE"}
    allowed_overall = {
        "ALIGNED_BULLISH", "ALIGNED_BEARISH", "MIXED", "INDETERMINATE",
    }
    for symbol, item in items.items():
        if not isinstance(symbol, str) or not isinstance(item, dict):
            return {"ok": False, "status": "INVALID_ANALYSIS_STATE"}
        health = item.get("data_health")
        timeframe = item.get("timeframe_state")
        if not isinstance(timeframe, dict):
            return {"ok": False, "status": "INVALID_ANALYSIS_STATE"}
        health_status = health.get("status") if isinstance(health, dict) else None
        if not isinstance(health_status, str):
            health_status = "DATA_UNAVAILABLE"

        compact_timeframe = {}
        for key in ("daily", "hourly", "15m"):
            value = timeframe.get(key)
            state = value.get("state") if isinstance(value, dict) else None
            evidence = value.get("evidence") if isinstance(value, dict) else None
            score = evidence.get("score") if isinstance(evidence, dict) else None
            valid_score = (
                score is None
                or (isinstance(score, (int, float))
                    and not isinstance(score, bool)
                    and math.isfinite(score))
            )
            if state not in allowed_states or not valid_score:
                return {"ok": False, "status": "INVALID_ANALYSIS_STATE"}
            compact_timeframe[key] = {"state": state, "score": score}

        overall = timeframe.get("overall")
        if overall not in allowed_overall:
            return {"ok": False, "status": "INVALID_ANALYSIS_STATE"}
        compact_timeframe["overall"] = overall
        symbols[symbol] = {
            "data_health": health_status,
            "timeframe_state": compact_timeframe,
        }

    overall_health = analysis_state.get("overall_data_health")
    if not isinstance(overall_health, str):
        overall_health = "DATA_UNAVAILABLE"
    return clean_json_value({
        "snapshot_time": snapshot_time,
        "account_alias": account_alias,
        "overall_data_health": overall_health,
        "symbols": symbols,
    })


def _is_valid_trigger_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return False
    if (not isinstance(snapshot.get("snapshot_time"), str)
            or not isinstance(snapshot.get("account_alias"), str)
            or not isinstance(snapshot.get("overall_data_health"), str)
            or not isinstance(snapshot.get("symbols"), dict)):
        return False
    allowed_states = {"BULLISH", "NEUTRAL", "BEARISH", "INDETERMINATE"}
    allowed_overall = {
        "ALIGNED_BULLISH", "ALIGNED_BEARISH", "MIXED", "INDETERMINATE",
    }
    for symbol, item in snapshot["symbols"].items():
        if (not isinstance(symbol, str) or not isinstance(item, dict)
                or not isinstance(item.get("data_health"), str)):
            return False
        timeframe = item.get("timeframe_state")
        if not isinstance(timeframe, dict) or timeframe.get("overall") not in allowed_overall:
            return False
        for key in ("daily", "hourly", "15m"):
            value = timeframe.get(key)
            if not isinstance(value, dict) or value.get("state") not in allowed_states:
                return False
            score = value.get("score")
            if (score is not None
                    and (not isinstance(score, (int, float))
                         or isinstance(score, bool)
                         or not math.isfinite(score))):
                return False
    return True


def _trigger_snapshot_for_compare(snapshot):
    """Adapt a validated compact snapshot without changing frozen trigger rules."""
    return {
        "ok": True,
        "snapshot_time": snapshot["snapshot_time"],
        "analysis_state": {
            symbol: {
                "data_health": {"status": item["data_health"]},
                "timeframe_state": {
                    "daily": {"state": item["timeframe_state"]["daily"]["state"]},
                    "hourly": {"state": item["timeframe_state"]["hourly"]["state"]},
                    "15m": {"state": item["timeframe_state"]["15m"]["state"]},
                    "overall": item["timeframe_state"]["overall"],
                },
            }
            for symbol, item in snapshot["symbols"].items()
        },
    }


def _is_valid_runtime_state(state):
    return (
        isinstance(state, dict)
        and state.get("schema_version") == RUNTIME_STATE_SCHEMA_VERSION
        and isinstance(state.get("updated_at"), str)
        and isinstance(state.get("account_alias"), str)
        and isinstance(state.get("last_trigger_events"), list)
        and _is_valid_event_runtime(state.get("event_runtime", {}))
        and _is_valid_trigger_snapshot(state.get("previous_snapshot"))
        and state["account_alias"] == state["previous_snapshot"]["account_alias"]
    )


def load_runtime_state():
    """Load and validate Runtime State Store v0.1 without modifying it."""
    try:
        with open(RUNTIME_STATE_PATH, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {"ok": True, "status": "NOT_FOUND", "state": None}
    except json.JSONDecodeError as error:
        return {"ok": False, "status": "CORRUPT_STATE", "error": str(error)}
    except OSError as error:
        return {"ok": False, "status": "READ_FAILED", "error": str(error)}

    if not isinstance(state, dict):
        return {"ok": False, "status": "CORRUPT_STATE"}
    if state.get("schema_version") != RUNTIME_STATE_SCHEMA_VERSION:
        return {"ok": False, "status": "SCHEMA_MISMATCH"}
    if not _is_valid_runtime_state(state):
        return {"ok": False, "status": "CORRUPT_STATE"}
    return {"ok": True, "status": "LOADED", "state": state}


def save_runtime_state(state):
    """Atomically save strict JSON in the runtime file's directory."""
    clean_state = clean_json_value(state)
    if not _is_valid_runtime_state(clean_state):
        return {"ok": False, "status": "INVALID_STATE"}

    runtime_dir = os.path.dirname(RUNTIME_STATE_PATH)
    temp_path = None
    try:
        os.makedirs(runtime_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=runtime_dir,
            prefix="runtime_state.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = handle.name
            json.dump(clean_state, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, RUNTIME_STATE_PATH)
        return {"ok": True, "status": "SAVED"}
    except (OSError, TypeError, ValueError) as error:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        return {"ok": False, "status": "SAVE_FAILED", "error": str(error)}


def build_ai_invocation_plan(actionable_events, analysis_state):
    """Build deterministic per-symbol AI requests without invoking any model."""
    severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}

    def result(ok=True, **values):
        return clean_json_value({
            "ok": ok,
            "should_invoke_ai": False,
            "request_count": 0,
            "highest_priority": None,
            "requests": [],
            "skipped": [],
            **values,
        })

    if not isinstance(actionable_events, list):
        return result(ok=False, status="INVALID_EVENTS")
    if (not isinstance(analysis_state, dict)
            or not isinstance(analysis_state.get("analysis_state"), dict)):
        return result(ok=False, status="INVALID_ANALYSIS_STATE")

    required_event_fields = (
        "symbol", "event_type", "severity", "previous",
        "current", "reason", "timestamp",
    )
    copied_events = []
    for event in actionable_events:
        if (not isinstance(event, dict)
                or event.get("severity") not in severity_rank
                or any(not isinstance(event.get(key), str)
                       for key in required_event_fields)):
            return result(ok=False, status="INVALID_EVENTS")
        copied_event = clean_json_value(dict(event))
        try:
            json.dumps(copied_event, allow_nan=False)
        except (TypeError, ValueError):
            return result(ok=False, status="INVALID_EVENTS")
        copied_events.append(copied_event)

    if not copied_events:
        return result(skipped=[{
            "symbol": None,
            "reason": "NO_ACTIONABLE_EVENTS",
            "event_types": [],
        }])

    events_by_symbol = {}
    for event in copied_events:
        events_by_symbol.setdefault(event["symbol"], []).append(event)

    items = analysis_state["analysis_state"]
    requests = []
    skipped = []

    def event_sort_key(event):
        return (
            event["event_type"], event["previous"], event["current"],
            event["severity"], event["timestamp"], event["reason"],
        )

    def add_skipped(symbol, reason, events):
        skipped.append({
            "symbol": symbol,
            "reason": reason,
            "event_types": sorted({event["event_type"] for event in events}),
        })

    for symbol in sorted(events_by_symbol):
        symbol_events = sorted(events_by_symbol[symbol], key=event_sort_key)
        item = items.get(symbol)
        health = item.get("data_health") if isinstance(item, dict) else None
        health_status = health.get("status") if isinstance(health, dict) else None
        if not isinstance(health_status, str):
            add_skipped(symbol, "INVALID_ANALYSIS_STATE", symbol_events)
            continue

        if health_status == "OK":
            selected_events = symbol_events
            analysis_mode = "MARKET_ANALYSIS"
            context_scope = "TRIGGERED_SYMBOL_ONLY"
        else:
            selected_events = [
                event for event in symbol_events
                if (event["event_type"] == "DATA_HEALTH_CHANGED"
                    and event["current"] != "OK")
            ]
            blocked_events = [
                event for event in symbol_events
                if event not in selected_events
            ]
            if blocked_events:
                add_skipped(symbol, "DATA_HEALTH_BLOCKED", blocked_events)
            if not selected_events:
                if not blocked_events:
                    add_skipped(symbol, "DATA_HEALTH_BLOCKED", symbol_events)
                continue
            analysis_mode = "DATA_QUALITY_ONLY"
            context_scope = "DATA_QUALITY_ONLY"

        priority = max(
            (event["severity"] for event in selected_events),
            key=severity_rank.get,
        )
        if priority == "HIGH":
            reason = "HIGH_ACTIONABLE_EVENT"
        elif priority == "MEDIUM":
            reason = "MEDIUM_ACTIONABLE_EVENT"
        elif len(selected_events) >= 2:
            reason = "MULTIPLE_LOW_EVENTS"
        else:
            add_skipped(symbol, "LOW_SEVERITY_ONLY", selected_events)
            continue

        requests.append({
            "symbol": symbol,
            "priority": priority,
            "analysis_mode": analysis_mode,
            "context_scope": context_scope,
            "reason": reason,
            "event_types": sorted({event["event_type"] for event in selected_events}),
            "selected_events": selected_events,
        })

    highest_priority = max(
        (request["priority"] for request in requests),
        key=severity_rank.get,
        default=None,
    )
    return result(
        should_invoke_ai=bool(requests),
        request_count=len(requests),
        highest_priority=highest_priority,
        requests=requests,
        skipped=sorted(
            skipped,
            key=lambda item: (
                "" if item["symbol"] is None else item["symbol"],
                item["reason"],
                item["event_types"],
            ),
        ),
    )


AI_REQUEST_SCHEMA_VERSION = 1
AI_RESPONSE_SCHEMA_VERSION = 1
AI_EXECUTION_PLAN_SCHEMA_VERSION = 1
LIVE_POSITION_MONITOR_SCOPE = "EXISTING_POSITIONS_ONLY"
MARKET_REGIME_SCHEMA_VERSION = 1
MARKET_REGIME_PROXY = "US.QQQ"

RELATIVE_STRENGTH_SCHEMA_VERSION = 1
RELATIVE_STRENGTH_DEFAULT_BENCHMARK = "US.QQQ"

PRICE_STRUCTURE_STATES = {
    "UPTREND", "DOWNTREND", "RANGE", "BREAKOUT", "BREAKDOWN",
    "PULLBACK", "RETEST", "STRUCTURE_DAMAGED", "INDETERMINATE",
}
STRUCTURE_INTEGRITY_STATES = {"INTACT", "WEAKENING", "BROKEN", "UNKNOWN"}
PRICE_LOCATION_STATES = {
    "AT_SUPPORT", "NEAR_SUPPORT", "MID_RANGE", "NEAR_RESISTANCE",
    "AT_RESISTANCE", "ABOVE_RESISTANCE", "BELOW_SUPPORT", "NO_CLEAR_LEVEL",
}
PRICE_STRUCTURE_REASON_CODES = {
    "HIGHER_HIGH_CONFIRMED", "HIGHER_LOW_CONFIRMED",
    "LOWER_HIGH_CONFIRMED", "LOWER_LOW_CONFIRMED",
    "RANGE_BOUNDARIES_CONFIRMED",
    "BREAKOUT_ABOVE_RESISTANCE", "BREAKDOWN_BELOW_SUPPORT",
    "PULLBACK_WITHIN_UPTREND", "PULLBACK_WITHIN_DOWNTREND",
    "RETESTING_BREAKOUT_LEVEL", "RETESTING_BREAKDOWN_LEVEL",
    "PRIMARY_STRUCTURE_INTACT", "PRIMARY_STRUCTURE_WEAKENING",
    "PRIMARY_STRUCTURE_BROKEN",
    "NEAR_MAJOR_SUPPORT", "NEAR_MAJOR_RESISTANCE",
    "INSUFFICIENT_SWINGS", "CONFLICTING_DUPLICATE_TIMESTAMP",
    "DATA_HEALTH_LIMITED",
    "HIGHER_LOW_BROKEN", "LOWER_HIGH_BROKEN",
    "INVALID_STRUCTURE_INPUT",
}
RELATIVE_STRENGTH_STATES = {
    "STRONG_OUTPERFORM", "OUTPERFORM", "NEUTRAL",
    "UNDERPERFORM", "STRONG_UNDERPERFORM", "INDETERMINATE",
}
RELATIVE_STRENGTH_DIRECTIONS = {
    "IMPROVING", "STABLE", "DETERIORATING", "UNKNOWN",
}
RELATIVE_STRENGTH_REASON_CODES = {
    "RELATIVE_5D_POSITIVE", "RELATIVE_5D_NEGATIVE",
    "RELATIVE_20D_POSITIVE", "RELATIVE_20D_NEGATIVE",
    "RELATIVE_60D_POSITIVE", "RELATIVE_60D_NEGATIVE",
    "RELATIVE_TREND_ABOVE_MA", "RELATIVE_TREND_BELOW_MA",
    "RELATIVE_MOMENTUM_IMPROVING", "RELATIVE_MOMENTUM_DETERIORATING",
    "HOURLY_CONFIRMATION_POSITIVE", "HOURLY_CONFIRMATION_NEGATIVE",
    "HOURLY_CONFIRMATION_NEUTRAL",
    "SHORT_TERM_RELATIVE_STRENGTH", "SHORT_TERM_RELATIVE_WEAKNESS",
    "SHORT_TERM_RELATIVE_NEUTRAL",
    "INSUFFICIENT_ALIGNED_BARS",
    "TARGET_DATA_HEALTH_LIMITED", "BENCHMARK_DATA_HEALTH_LIMITED",
    "SELF_BENCHMARK", "DAILY_RS_INDETERMINATE", "RS_SCORE_CLAMPED",
    "RELATIVE_DIRECTION_IMPROVING", "RELATIVE_DIRECTION_DETERIORATING",
    "RELATIVE_DIRECTION_STABLE", "RELATIVE_DIRECTION_UNKNOWN",
    "INVALID_RS_INPUT", "CONFLICTING_DUPLICATE_TIMESTAMP",
}
AI_ANALYSIS_STATUSES = {
    "OK", "AI_UNAVAILABLE", "INVALID_REQUEST", "INVALID_RESPONSE",
    "TIMEOUT", "PROVIDER_ERROR", "DATA_QUALITY_ONLY",
}
AI_DECISION_STATES = {
    "HOLD", "WATCH", "ADD_CANDIDATE", "REDUCE_CANDIDATE", "RISK_ALERT",
}
AI_TIMEFRAME_STATES = {
    "BULLISH", "NEUTRAL", "BEARISH", "INDETERMINATE",
    "ALIGNED_BULLISH", "ALIGNED_BEARISH", "MIXED",
}
AI_FAILURE_STATUSES = {
    "AI_UNAVAILABLE", "TIMEOUT", "PROVIDER_ERROR", "INVALID_RESPONSE",
}
FALLBACK_ELIGIBLE_STATUSES = {
    "AI_UNAVAILABLE", "TIMEOUT", "PROVIDER_ERROR", "INVALID_RESPONSE",
}
CLAUDE_DEFAULT_MODEL = "claude-sonnet-5"
CLAUDE_DEFAULT_TIMEOUT_SECONDS = 30.0
CLAUDE_DEFAULT_MAX_TOKENS = 1200
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"
DEEPSEEK_DEFAULT_TIMEOUT_SECONDS = 30.0
DEEPSEEK_DEFAULT_MAX_TOKENS = 1200

CLAUDE_SYSTEM_PROMPT = """You are a real-time position analysis component, not a trade execution system.
Use only the supplied structured evidence. Distinguish FACT from INFERENCE in evidence details.
Treat the supplied deterministic data_health.status as authoritative. Do not independently classify data as stale
solely from calendar-time gaps such as weekends, holidays, or non-trading sessions. When data_health.status is OK,
do not emit STALE_DATA merely because the latest timestamp predates the request time.
Do not invent missing or real-time data, recalculate deterministic indicators, override Timeframe State,
create orders, claim a trade occurred, place trades, or call tools. decision_state is an analysis state,
not a trading command. ADD_CANDIDATE and REDUCE_CANDIDATE are candidate states only. Keep short_rationale concise."""

CLAUDE_DATA_QUALITY_PROMPT = """This is DATA_QUALITY_ONLY. Analyze only source completeness,
timestamp anomalies, conclusions that cannot currently be formed, and whether data recovery should be awaited.
Do not assess market direction or produce directional candidate states."""

DEEPSEEK_SYSTEM_PROMPT = """You are a real-time position analysis component, not a trade execution system.
Return JSON only, using exactly this JSON shape:
{"decision_state":"WATCH","confidence":50,"timeframe_view":{"daily":"BULLISH","hourly":"NEUTRAL","15m":"BEARISH","overall":"MIXED"},"risk_flags":[],"evidence":[{"type":"FACT","detail":"Concise supplied evidence."}],"short_rationale":"Concise rationale."}
Use only the supplied structured evidence. Distinguish FACT from INFERENCE in evidence details.
Treat the supplied deterministic data_health.status as authoritative. Do not independently classify data as stale
solely from calendar-time gaps such as weekends, holidays, or non-trading sessions. When data_health.status is OK,
do not emit STALE_DATA merely because the latest timestamp predates the request time.
Do not invent missing or real-time data, recalculate deterministic indicators, override Timeframe State,
create orders, claim a trade occurred, place trades, or call tools. decision_state is an analysis state,
not a trading command. ADD_CANDIDATE and REDUCE_CANDIDATE are candidate states only. Keep short_rationale concise."""

DEEPSEEK_DATA_QUALITY_PROMPT = """This is DATA_QUALITY_ONLY. Analyze only source completeness,
timestamp anomalies, conclusions that cannot currently be formed, and whether data recovery should be awaited.
Do not assess market direction or produce directional candidate states. Return WATCH and set every timeframe_view
value to INDETERMINATE."""


def validate_ai_request(request):
    """Validate the common AI request schema."""
    errors = []
    if not isinstance(request, dict):
        return {"ok": False, "errors": ["REQUEST_NOT_OBJECT"]}
    required_strings = (
        "request_id", "created_at", "symbol", "priority",
        "analysis_mode", "context_scope",
    )
    for key in required_strings:
        if not isinstance(request.get(key), str) or not request.get(key):
            errors.append(f"INVALID_{key.upper()}")
    if request.get("schema_version") != AI_REQUEST_SCHEMA_VERSION:
        errors.append("INVALID_SCHEMA_VERSION")
    if request.get("priority") not in ("HIGH", "MEDIUM", "LOW"):
        errors.append("INVALID_PRIORITY")
    if request.get("analysis_mode") not in ("MARKET_ANALYSIS", "DATA_QUALITY_ONLY"):
        errors.append("INVALID_ANALYSIS_MODE")
    expected_scope = (
        "DATA_QUALITY_ONLY"
        if request.get("analysis_mode") == "DATA_QUALITY_ONLY"
        else "TRIGGERED_SYMBOL_ONLY"
    )
    if request.get("context_scope") != expected_scope:
        errors.append("INVALID_CONTEXT_SCOPE")

    trigger = request.get("trigger")
    if (not isinstance(trigger, dict)
            or not isinstance(trigger.get("event_types"), list)
            or not all(isinstance(value, str) for value in trigger.get("event_types", []))
            or not isinstance(trigger.get("selected_events"), list)):
        errors.append("INVALID_TRIGGER")
    health = request.get("data_health")
    if not isinstance(health, dict) or not isinstance(health.get("status"), str):
        errors.append("INVALID_DATA_HEALTH")

    if request.get("analysis_mode") == "MARKET_ANALYSIS":
        for key in ("position", "market", "timeframe_state", "indicators", "recent_structure"):
            if not isinstance(request.get(key), dict):
                errors.append(f"INVALID_{key.upper()}")
        timeframe = request.get("timeframe_state")
        if isinstance(timeframe, dict):
            if timeframe.get("overall") not in {
                "ALIGNED_BULLISH", "ALIGNED_BEARISH", "MIXED", "INDETERMINATE",
            }:
                errors.append("INVALID_TIMEFRAME_OVERALL")
            for key in ("daily", "hourly", "15m"):
                value = timeframe.get(key)
                if (not isinstance(value, dict)
                        or value.get("state") not in {
                            "BULLISH", "NEUTRAL", "BEARISH", "INDETERMINATE",
                        }):
                    errors.append(f"INVALID_TIMEFRAME_{key.upper()}")
        recent = request.get("recent_structure")
        if isinstance(recent, dict):
            for key in ("daily", "hourly", "15m"):
                bars = recent.get(key)
                if not isinstance(bars, list) or len(bars) > 5:
                    errors.append(f"INVALID_RECENT_STRUCTURE_{key.upper()}")
    else:
        forbidden = {
            "position", "market", "timeframe_state", "indicators", "recent_structure",
        }
        if forbidden & request.keys():
            errors.append("DATA_QUALITY_REQUEST_HAS_MARKET_CONTEXT")

    try:
        json.dumps(request, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("NOT_STRICT_JSON")
    return {"ok": not errors, "errors": errors}


def build_ai_analysis_request(invocation_request, analysis_state):
    """Build one compact, deterministic common AI request for one symbol."""
    if (not isinstance(invocation_request, dict)
            or not isinstance(analysis_state, dict)
            or not isinstance(analysis_state.get("analysis_state"), dict)):
        return {"ok": False, "status": "INVALID_REQUEST_INPUT"}
    symbol = invocation_request.get("symbol")
    item = analysis_state["analysis_state"].get(symbol)
    selected_events = invocation_request.get("selected_events")
    event_types = invocation_request.get("event_types")
    if (not isinstance(symbol, str)
            or not isinstance(item, dict)
            or not isinstance(selected_events, list)
            or not isinstance(event_types, list)
            or not all(isinstance(value, str) for value in event_types)
            or invocation_request.get("priority") not in ("HIGH", "MEDIUM", "LOW")
            or invocation_request.get("analysis_mode") not in (
                "MARKET_ANALYSIS", "DATA_QUALITY_ONLY",
            )
            or not isinstance(analysis_state.get("snapshot_time"), str)):
        return {"ok": False, "status": "INVALID_REQUEST_INPUT"}
    fingerprints = [build_event_fingerprint(event) for event in selected_events]
    if any(value is None for value in fingerprints):
        return {"ok": False, "status": "INVALID_REQUEST_INPUT"}
    request_identity = {
        "snapshot_time": analysis_state["snapshot_time"],
        "symbol": symbol,
        "event_fingerprints": sorted(fingerprints),
    }
    request_id = hashlib.sha256(
        json.dumps(
            request_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    health = item.get("data_health")
    health = health if isinstance(health, dict) else {}
    common = {
        "schema_version": AI_REQUEST_SCHEMA_VERSION,
        "request_id": request_id,
        "created_at": analysis_state["snapshot_time"],
        "symbol": symbol,
        "priority": invocation_request.get("priority"),
        "analysis_mode": invocation_request.get("analysis_mode"),
        "context_scope": invocation_request.get("context_scope"),
        "trigger": {
            "event_types": sorted(set(event_types)),
            "selected_events": sorted(
                (clean_json_value(dict(event)) for event in selected_events),
                key=lambda event: (
                    event.get("event_type", ""), event.get("previous", ""),
                    event.get("current", ""), event.get("severity", ""),
                    event.get("timestamp", ""), event.get("reason", ""),
                ),
            ),
        },
        "data_health": {
            "status": health.get("status"),
            "latest_times": clean_json_value(health.get("latest_times")),
            "source_status": (
                item.get("market", {}).get("status")
                if isinstance(item.get("market"), dict) else None
            ),
        },
    }

    if invocation_request.get("analysis_mode") == "MARKET_ANALYSIS":
        bars = item.get("bars") if isinstance(item.get("bars"), dict) else {}
        allowed_bar_fields = ("time_key", "open", "high", "low", "close", "volume")
        recent_structure = {}
        for timeframe in ("daily", "hourly", "15m"):
            timeframe_bars = bars.get(timeframe, [])
            if not isinstance(timeframe_bars, list):
                timeframe_bars = []
            recent_structure[timeframe] = [
                {key: row.get(key) for key in allowed_bar_fields}
                for row in timeframe_bars[-5:]
                if isinstance(row, dict)
            ]
        position = item.get("position") if isinstance(item.get("position"), dict) else {}
        market = item.get("market") if isinstance(item.get("market"), dict) else {}
        common.update({
            "position": {
                key: position.get(key)
                for key in (
                    "quantity", "cost_price", "market_price", "market_value",
                    "pnl", "pnl_ratio",
                )
            },
            "market": {
                key: market.get(key)
                for key in ("last_price", "change_rate_pct", "volume", "volume_ratio")
            },
            "timeframe_state": clean_json_value(item.get("timeframe_state")),
            "indicators": clean_json_value(item.get("indicators")),
            "recent_structure": clean_json_value(recent_structure),
        })

    request = clean_json_value(common)
    validation = validate_ai_request(request)
    if not validation["ok"]:
        return {
            "ok": False,
            "status": "INVALID_REQUEST",
            "validation_errors": validation["errors"],
        }
    return request


def validate_ai_response(response):
    """Validate the common AI response and its success/error contract."""
    errors = []
    if not isinstance(response, dict):
        return {"ok": False, "errors": ["RESPONSE_NOT_OBJECT"]}
    required = {
        "schema_version", "request_id", "provider", "model", "analysis_status",
        "decision_state", "confidence", "timeframe_view", "risk_flags",
        "evidence", "short_rationale", "generated_at", "error",
    }
    for key in sorted(required - response.keys()):
        errors.append(f"MISSING_{key.upper()}")
    if response.get("schema_version") != AI_RESPONSE_SCHEMA_VERSION:
        errors.append("INVALID_SCHEMA_VERSION")
    for key in ("request_id", "provider", "model", "short_rationale", "generated_at"):
        if not isinstance(response.get(key), str) or not response.get(key):
            errors.append(f"INVALID_{key.upper()}")
    status = response.get("analysis_status")
    if status not in AI_ANALYSIS_STATUSES:
        errors.append("INVALID_ANALYSIS_STATUS")
    if response.get("decision_state") not in AI_DECISION_STATES:
        errors.append("INVALID_DECISION_STATE")
    confidence = response.get("confidence")
    if (not isinstance(confidence, int)
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 100):
        errors.append("INVALID_CONFIDENCE")
    timeframe = response.get("timeframe_view")
    if (not isinstance(timeframe, dict)
            or set(timeframe) != {"daily", "hourly", "15m", "overall"}
            or any(timeframe.get(key) not in {
                "BULLISH", "NEUTRAL", "BEARISH", "INDETERMINATE",
            } for key in ("daily", "hourly", "15m"))
            or timeframe.get("overall") not in {
                "ALIGNED_BULLISH", "ALIGNED_BEARISH", "MIXED", "INDETERMINATE",
            }):
        errors.append("INVALID_TIMEFRAME_VIEW")
    risk_flags = response.get("risk_flags")
    if not isinstance(risk_flags, list) or not all(isinstance(value, str) for value in risk_flags):
        errors.append("INVALID_RISK_FLAGS")
    evidence = response.get("evidence")
    if (not isinstance(evidence, list)
            or any(not isinstance(value, dict)
                   or not isinstance(value.get("type"), str)
                   or not isinstance(value.get("detail"), str)
                   for value in evidence)):
        errors.append("INVALID_EVIDENCE")
    error = response.get("error")
    success_status = status in ("OK", "DATA_QUALITY_ONLY")
    if success_status and error is not None:
        errors.append("SUCCESS_RESPONSE_HAS_ERROR")
    if (not success_status
            and (not isinstance(error, dict)
                 or not isinstance(error.get("code"), str)
                 or not isinstance(error.get("message"), str))):
        errors.append("ERROR_RESPONSE_MISSING_ERROR")
    try:
        json.dumps(response, allow_nan=False)
    except (TypeError, ValueError):
        errors.append("NOT_STRICT_JSON")
    return {"ok": not errors, "errors": errors}


def _error_ai_response(request, provider, status, code, message):
    request_id = request.get("request_id") if isinstance(request, dict) else None
    generated_at = request.get("created_at") if isinstance(request, dict) else None
    return {
        "schema_version": AI_RESPONSE_SCHEMA_VERSION,
        "request_id": request_id if isinstance(request_id, str) and request_id else "INVALID_REQUEST",
        "provider": provider,
        "model": "mock",
        "analysis_status": status,
        "decision_state": "WATCH",
        "confidence": 0,
        "timeframe_view": {
            "daily": "INDETERMINATE",
            "hourly": "INDETERMINATE",
            "15m": "INDETERMINATE",
            "overall": "INDETERMINATE",
        },
        "risk_flags": [status],
        "evidence": [],
        "short_rationale": message,
        "generated_at": generated_at if isinstance(generated_at, str) and generated_at else "UNKNOWN",
        "error": {"code": code, "message": message},
    }


class AIModelAdapter:
    provider_name = "UNKNOWN"

    def analyze(self, request):
        raise NotImplementedError


class _DeterministicMockAdapter(AIModelAdapter):
    confidence_by_overall = {}
    decision_by_overall = {}

    def __init__(self, forced_status=None):
        self.forced_status = forced_status

    def analyze(self, request):
        validation = validate_ai_request(request)
        if not validation["ok"]:
            return _error_ai_response(
                request, self.provider_name, "INVALID_REQUEST",
                "INVALID_REQUEST", "; ".join(validation["errors"]),
            )
        if self.forced_status is not None:
            if self.forced_status not in AI_FAILURE_STATUSES:
                return _error_ai_response(
                    request, self.provider_name, "PROVIDER_ERROR",
                    "INVALID_FORCED_STATUS", "Unsupported mock failure status.",
                )
            return _error_ai_response(
                request, self.provider_name, self.forced_status,
                f"MOCK_{self.forced_status}",
                f"{self.provider_name} mock returned {self.forced_status}.",
            )
        if request["analysis_mode"] == "DATA_QUALITY_ONLY":
            return {
                "schema_version": AI_RESPONSE_SCHEMA_VERSION,
                "request_id": request["request_id"],
                "provider": self.provider_name,
                "model": "mock",
                "analysis_status": "DATA_QUALITY_ONLY",
                "decision_state": "WATCH",
                "confidence": 100,
                "timeframe_view": {
                    "daily": "INDETERMINATE", "hourly": "INDETERMINATE",
                    "15m": "INDETERMINATE", "overall": "INDETERMINATE",
                },
                "risk_flags": ["DATA_QUALITY_ISSUE"],
                "evidence": [{
                    "type": "DATA_HEALTH",
                    "detail": f"Current status: {request['data_health']['status']}",
                }],
                "short_rationale": "Review data quality before market analysis.",
                "generated_at": request["created_at"],
                "error": None,
            }

        timeframe = request["timeframe_state"]
        overall = timeframe["overall"]
        decision = self.decision_by_overall.get(overall, "WATCH")
        confidence = self.confidence_by_overall.get(overall, 50)
        risk_flags = []
        if overall == "MIXED":
            risk_flags.append("TIMEFRAME_DIVERGENCE")
        elif overall == "ALIGNED_BEARISH":
            risk_flags.append("ALIGNED_BEARISH_STRUCTURE")
        elif overall == "INDETERMINATE":
            risk_flags.append("INDETERMINATE_STRUCTURE")
        return {
            "schema_version": AI_RESPONSE_SCHEMA_VERSION,
            "request_id": request["request_id"],
            "provider": self.provider_name,
            "model": "mock",
            "analysis_status": "OK",
            "decision_state": decision,
            "confidence": confidence,
            "timeframe_view": {
                "daily": timeframe["daily"]["state"],
                "hourly": timeframe["hourly"]["state"],
                "15m": timeframe["15m"]["state"],
                "overall": overall,
            },
            "risk_flags": risk_flags,
            "evidence": [{
                "type": "TIMEFRAME_STATE",
                "detail": (
                    f"Daily {timeframe['daily']['state']}; hourly "
                    f"{timeframe['hourly']['state']}; 15m {timeframe['15m']['state']}."
                ),
            }],
            "short_rationale": f"Deterministic mock summary for {overall}.",
            "generated_at": request["created_at"],
            "error": None,
        }


class ClaudeMockAdapter(_DeterministicMockAdapter):
    provider_name = "CLAUDE"
    confidence_by_overall = {
        "ALIGNED_BULLISH": 78, "ALIGNED_BEARISH": 82,
        "MIXED": 70, "INDETERMINATE": 50,
    }
    decision_by_overall = {
        "ALIGNED_BULLISH": "ADD_CANDIDATE",
        "ALIGNED_BEARISH": "RISK_ALERT",
        "MIXED": "WATCH",
        "INDETERMINATE": "WATCH",
    }


class DeepSeekMockAdapter(_DeterministicMockAdapter):
    provider_name = "DEEPSEEK"
    confidence_by_overall = {
        "ALIGNED_BULLISH": 72, "ALIGNED_BEARISH": 76,
        "MIXED": 65, "INDETERMINATE": 45,
    }
    decision_by_overall = {
        "ALIGNED_BULLISH": "WATCH",
        "ALIGNED_BEARISH": "REDUCE_CANDIDATE",
        "MIXED": "WATCH",
        "INDETERMINATE": "WATCH",
    }


def _claude_analysis_payload_schema(analysis_mode):
    directional_states = ["BULLISH", "NEUTRAL", "BEARISH", "INDETERMINATE"]
    overall_states = [
        "ALIGNED_BULLISH", "ALIGNED_BEARISH", "MIXED", "INDETERMINATE",
    ]
    if analysis_mode == "DATA_QUALITY_ONLY":
        decision_states = ["WATCH"]
        directional_states = ["INDETERMINATE"]
        overall_states = ["INDETERMINATE"]
    else:
        decision_states = sorted(AI_DECISION_STATES)
    return {
        "type": "object",
        "properties": {
            "decision_state": {"type": "string", "enum": decision_states},
            "confidence": {"type": "integer"},
            "timeframe_view": {
                "type": "object",
                "properties": {
                    "daily": {"type": "string", "enum": directional_states},
                    "hourly": {"type": "string", "enum": directional_states},
                    "15m": {"type": "string", "enum": directional_states},
                    "overall": {"type": "string", "enum": overall_states},
                },
                "required": ["daily", "hourly", "15m", "overall"],
                "additionalProperties": False,
            },
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "detail": {"type": "string"},
                    },
                    "required": ["type", "detail"],
                    "additionalProperties": False,
                },
            },
            "short_rationale": {"type": "string"},
        },
        "required": [
            "decision_state", "confidence", "timeframe_view",
            "risk_flags", "evidence", "short_rationale",
        ],
        "additionalProperties": False,
    }


class ClaudeRealAdapter(AIModelAdapter):
    provider_name = "CLAUDE"

    def __init__(self, client=None, environ=None, client_factory=None, now_provider=None):
        self._client = client
        self._environ = os.environ if environ is None else environ
        self._client_factory = Anthropic if client_factory is None else client_factory
        self._now_provider = datetime.now if now_provider is None else now_provider
        self.model = self._environ.get("CLAUDE_MODEL") or CLAUDE_DEFAULT_MODEL
        self.timeout_seconds = self._read_positive_number(
            "CLAUDE_TIMEOUT_SECONDS", CLAUDE_DEFAULT_TIMEOUT_SECONDS, float,
        )
        self.max_tokens = self._read_positive_number(
            "CLAUDE_MAX_TOKENS", CLAUDE_DEFAULT_MAX_TOKENS, int,
        )

    def _read_positive_number(self, name, default, converter):
        raw_value = self._environ.get(name)
        if raw_value in (None, ""):
            return default
        try:
            value = converter(raw_value)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    @staticmethod
    def _safe_error_text(value, max_length):
        if not isinstance(value, str):
            return None
        text = " ".join(value.split())
        if not text:
            return None
        lowered = text.lower()
        if all(marker in lowered for marker in (
                '"schema_version"', '"request_id"', '"trigger"')):
            return "[REDACTED_COMMON_AI_REQUEST]"
        text = re.sub("sk" + r"-ant-[A-Za-z0-9_-]+", "[REDACTED_API_KEY]", text)
        text = re.sub(
            r"(?i)((?:authorization|x-api-key|api[_ -]?key)\s*[:=]\s*)"
            r"(?:bearer\s+)?[^\s,;}]+",
            r"\1[REDACTED]",
            text,
        )
        return text if len(text) <= max_length else text[:max_length] + "...[TRUNCATED]"

    @classmethod
    def _status_error_details(cls, error):
        details = {"status_code": error.status_code}
        body = error.body if isinstance(error.body, dict) else {}
        body_error = body.get("error") if isinstance(body.get("error"), dict) else {}
        request_id = getattr(error, "request_id", None)
        if not request_id:
            request_id = body.get("request_id")
        if not request_id and getattr(error, "response", None) is not None:
            request_id = error.response.headers.get("request-id")
        request_id = cls._safe_error_text(request_id, 200)
        error_type = cls._safe_error_text(
            body_error.get("type") or getattr(error, "type", None), 100,
        )
        provider_message = cls._safe_error_text(body_error.get("message"), 1000)
        if request_id:
            details["request_id"] = request_id
        if error_type:
            details["type"] = error_type
        if provider_message:
            details["message"] = provider_message
        return details

    def _error(self, request, status, code, message, details=None):
        response = _error_ai_response(request, self.provider_name, status, code, message)
        response["model"] = self.model
        response["generated_at"] = self._now_provider().isoformat()
        if details:
            response["error"].update(details)
        return response

    def _get_client(self, api_key):
        if self._client is None:
            self._client = self._client_factory(
                api_key=api_key,
                timeout=self.timeout_seconds,
                max_retries=0,
            )
        return self._client

    def analyze(self, request):
        validation = validate_ai_request(request)
        if not validation["ok"]:
            return self._error(
                request, "INVALID_REQUEST", "INVALID_REQUEST",
                "; ".join(validation["errors"]),
            )
        api_key = self._environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return self._error(
                request, "AI_UNAVAILABLE", "ANTHROPIC_API_KEY_MISSING",
                "Anthropic API key is not configured.",
            )

        system_prompt = CLAUDE_SYSTEM_PROMPT
        if request["analysis_mode"] == "DATA_QUALITY_ONLY":
            system_prompt += "\n" + CLAUDE_DATA_QUALITY_PROMPT
        user_content = (
            "Analyze this Common AI Request.\n"
            + json.dumps(
                request,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        stage = "START"
        try:
            message = self._get_client(api_key).messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                thinking={"type": "disabled"},
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": _claude_analysis_payload_schema(request["analysis_mode"]),
                    }
                },
            )
            stage = "EXTRACT_CONTENT"
            text = None
            for block in message.content:
                block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                if block_type == "text":
                    stage = "EXTRACT_TEXT"
                    text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
                    break
            stage = "JSON_LOAD"
            payload = json.loads(text) if isinstance(text, str) else None
            stage = "PAYLOAD_SHAPE_CHECK"
            expected_payload_fields = {
                "decision_state", "confidence", "timeframe_view",
                "risk_flags", "evidence", "short_rationale",
            }
            if not isinstance(payload, dict) or set(payload) != expected_payload_fields:
                actual_keys = (
                    sorted(payload.keys()) if isinstance(payload, dict)
                    else type(payload).__name__
                )
                return self._error(
                    request, "INVALID_RESPONSE", "ANTHROPIC_INVALID_RESPONSE",
                    "Anthropic response failed internal schema validation.",
                    details={
                        "validation_errors": ["INVALID_PAYLOAD_SHAPE"],
                        "expected_keys": sorted(expected_payload_fields),
                        "actual_keys": actual_keys,
                    },
                )
            stage = "BUILD_COMMON_RESPONSE"
            response = {
                "schema_version": AI_RESPONSE_SCHEMA_VERSION,
                "request_id": request["request_id"],
                "provider": self.provider_name,
                "model": self.model,
                "analysis_status": (
                    "DATA_QUALITY_ONLY"
                    if request["analysis_mode"] == "DATA_QUALITY_ONLY" else "OK"
                ),
                **payload,
                "generated_at": self._now_provider().isoformat(),
                "error": None,
            }
            stage = "VALIDATE_COMMON_RESPONSE"
            response_validation = validate_ai_response(response)
            data_quality_invalid = (
                request["analysis_mode"] == "DATA_QUALITY_ONLY"
                and (response["decision_state"] != "WATCH"
                     or set(response["timeframe_view"].values()) != {"INDETERMINATE"})
            )
            if not response_validation["ok"] or data_quality_invalid:
                diag_errors = list(response_validation["errors"])
                if data_quality_invalid:
                    diag_errors.append("DATA_QUALITY_ONLY_STATE_MISMATCH")
                return self._error(
                    request, "INVALID_RESPONSE", "ANTHROPIC_INVALID_RESPONSE",
                    "Anthropic response failed internal schema validation.",
                    details={"validation_errors": diag_errors},
                )
            return response
        except APITimeoutError:
            return self._error(
                request, "TIMEOUT", "ANTHROPIC_TIMEOUT", "Anthropic request timed out.",
            )
        except APIConnectionError:
            return self._error(
                request, "AI_UNAVAILABLE", "ANTHROPIC_CONNECTION_ERROR",
                "Anthropic service could not be reached.",
            )
        except APIStatusError as error:
            status_code = error.status_code
            details = self._status_error_details(error)
            if status_code == 429:
                return self._error(
                    request, "AI_UNAVAILABLE", "ANTHROPIC_RATE_LIMIT",
                    details.get("message", "Anthropic rate limit is active."), details,
                )
            if status_code == 529:
                return self._error(
                    request, "AI_UNAVAILABLE", "ANTHROPIC_OVERLOADED",
                    details.get("message", "Anthropic service is overloaded."), details,
                )
            if status_code == 401:
                return self._error(
                    request, "PROVIDER_ERROR", "ANTHROPIC_AUTHENTICATION_ERROR",
                    details.get("message", "Anthropic authentication failed."), details,
                )
            if status_code == 403:
                return self._error(
                    request, "PROVIDER_ERROR", "ANTHROPIC_PERMISSION_ERROR",
                    details.get("message", "Anthropic permission was denied."), details,
                )
            if status_code == 400:
                return self._error(
                    request, "INVALID_REQUEST", "ANTHROPIC_BAD_REQUEST",
                    details.get("message", "Anthropic rejected the request."), details,
                )
            if status_code == 422:
                return self._error(
                    request, "INVALID_REQUEST", "ANTHROPIC_UNPROCESSABLE_ENTITY",
                    details.get("message", "Anthropic could not process the request."), details,
                )
            if status_code >= 500:
                return self._error(
                    request, "PROVIDER_ERROR", "ANTHROPIC_SERVER_ERROR",
                    details.get("message", "Anthropic server error."), details,
                )
            return self._error(
                request, "PROVIDER_ERROR", "ANTHROPIC_API_ERROR",
                details.get("message", "Anthropic API returned an unexpected status."), details,
            )
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as exc:
            diag_details = {
                "diagnostic_stage": stage,
                "exception_type": type(exc).__name__,
            }
            if isinstance(exc, json.JSONDecodeError):
                diag_details["json_error_position"] = {
                    "line": exc.lineno,
                    "column": exc.colno,
                    "char_offset": exc.pos,
                }
            return self._error(
                request, "INVALID_RESPONSE", "ANTHROPIC_INVALID_RESPONSE",
                "Anthropic returned an invalid structured response.",
                details=diag_details,
            )
        except Exception:
            return self._error(
                request, "PROVIDER_ERROR", "ANTHROPIC_UNKNOWN_ERROR",
                "Anthropic transport returned an unexpected error.",
            )


class DeepSeekRealAdapter(AIModelAdapter):
    provider_name = "DEEPSEEK"

    def __init__(self, client=None, environ=None, client_factory=None, now_provider=None):
        self._client = client
        self._environ = os.environ if environ is None else environ
        self._client_factory = OpenAI if client_factory is None else client_factory
        self._now_provider = datetime.now if now_provider is None else now_provider
        self.model = self._environ.get("DEEPSEEK_MODEL") or DEEPSEEK_DEFAULT_MODEL
        self.timeout_seconds = self._read_positive_number(
            "DEEPSEEK_TIMEOUT_SECONDS", DEEPSEEK_DEFAULT_TIMEOUT_SECONDS, float,
        )
        self.max_tokens = self._read_positive_number(
            "DEEPSEEK_MAX_TOKENS", DEEPSEEK_DEFAULT_MAX_TOKENS, int,
        )

    def _read_positive_number(self, name, default, converter):
        raw_value = self._environ.get(name)
        if raw_value in (None, ""):
            return default
        try:
            value = converter(raw_value)
        except (TypeError, ValueError):
            return default
        return value if value > 0 else default

    @staticmethod
    def _safe_error_text(value, max_length):
        if not isinstance(value, str):
            return None
        text = " ".join(value.split())
        if not text:
            return None
        lowered = text.lower()
        if all(marker in lowered for marker in (
                '"schema_version"', '"request_id"', '"trigger"')):
            return "[REDACTED_COMMON_AI_REQUEST]"
        text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED_API_KEY]", text)
        text = re.sub(
            r"(?i)((?:authorization|api[_ -]?key)\s*[:=]\s*)"
            r"(?:bearer\s+)?[^\s,;}]+",
            r"\1[REDACTED]",
            text,
        )
        return text if len(text) <= max_length else text[:max_length] + "...[TRUNCATED]"

    @classmethod
    def _status_error_details(cls, error):
        details = {"status_code": error.status_code}
        body = error.body if isinstance(error.body, dict) else {}
        body_error = body.get("error") if isinstance(body.get("error"), dict) else body
        request_id = getattr(error, "request_id", None)
        if not request_id:
            request_id = body.get("request_id")
        if not request_id and getattr(error, "response", None) is not None:
            request_id = (
                error.response.headers.get("x-request-id")
                or error.response.headers.get("request-id")
            )
        request_id = cls._safe_error_text(request_id, 200)
        error_type = cls._safe_error_text(body_error.get("type"), 100)
        provider_message = cls._safe_error_text(body_error.get("message"), 1000)
        if request_id:
            details["request_id"] = request_id
        if error_type:
            details["type"] = error_type
        if provider_message:
            details["message"] = provider_message
        return details

    def _error(self, request, status, code, message, details=None):
        response = _error_ai_response(request, self.provider_name, status, code, message)
        response["model"] = self.model
        response["generated_at"] = self._now_provider().isoformat()
        if details:
            response["error"].update(details)
        return response

    def _get_client(self, api_key):
        if self._client is None:
            self._client = self._client_factory(
                api_key=api_key,
                base_url=DEEPSEEK_BASE_URL,
                timeout=self.timeout_seconds,
                max_retries=0,
            )
        return self._client

    def analyze(self, request):
        validation = validate_ai_request(request)
        if not validation["ok"]:
            return self._error(
                request, "INVALID_REQUEST", "INVALID_REQUEST",
                "; ".join(validation["errors"]),
            )
        api_key = self._environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return self._error(
                request, "AI_UNAVAILABLE", "DEEPSEEK_API_KEY_MISSING",
                "DeepSeek API key is not configured.",
            )

        system_prompt = DEEPSEEK_SYSTEM_PROMPT
        if request["analysis_mode"] == "DATA_QUALITY_ONLY":
            system_prompt += "\n" + DEEPSEEK_DATA_QUALITY_PROMPT
        user_content = (
            "Analyze this Common AI Request and return the required JSON.\n"
            + json.dumps(
                request,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        stage = "START"
        try:
            completion = self._get_client(api_key).chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                stream=False,
                extra_body={"thinking": {"type": "disabled"}},
            )
            stage = "EXTRACT_CONTENT"
            text = completion.choices[0].message.content
            if not isinstance(text, str) or not text.strip():
                return self._error(
                    request, "INVALID_RESPONSE", "DEEPSEEK_INVALID_RESPONSE",
                    "DeepSeek returned empty model content.",
                    details={
                        "diagnostic_stage": stage,
                        "validation_errors": ["EMPTY_MODEL_CONTENT"],
                    },
                )
            stage = "JSON_LOAD"
            payload = json.loads(text)
            stage = "PAYLOAD_SHAPE_CHECK"
            expected_payload_fields = {
                "decision_state", "confidence", "timeframe_view",
                "risk_flags", "evidence", "short_rationale",
            }
            if not isinstance(payload, dict) or set(payload) != expected_payload_fields:
                actual_keys = (
                    sorted(payload.keys()) if isinstance(payload, dict)
                    else type(payload).__name__
                )
                return self._error(
                    request, "INVALID_RESPONSE", "DEEPSEEK_INVALID_RESPONSE",
                    "DeepSeek response failed internal schema validation.",
                    details={
                        "validation_errors": ["INVALID_PAYLOAD_SHAPE"],
                        "expected_keys": sorted(expected_payload_fields),
                        "actual_keys": actual_keys,
                    },
                )
            stage = "BUILD_COMMON_RESPONSE"
            response = {
                "schema_version": AI_RESPONSE_SCHEMA_VERSION,
                "request_id": request["request_id"],
                "provider": self.provider_name,
                "model": self.model,
                "analysis_status": (
                    "DATA_QUALITY_ONLY"
                    if request["analysis_mode"] == "DATA_QUALITY_ONLY" else "OK"
                ),
                **payload,
                "generated_at": self._now_provider().isoformat(),
                "error": None,
            }
            stage = "VALIDATE_COMMON_RESPONSE"
            response_validation = validate_ai_response(response)
            data_quality_invalid = (
                request["analysis_mode"] == "DATA_QUALITY_ONLY"
                and (response["decision_state"] != "WATCH"
                     or set(response["timeframe_view"].values()) != {"INDETERMINATE"})
            )
            if not response_validation["ok"] or data_quality_invalid:
                diag_errors = list(response_validation["errors"])
                if data_quality_invalid:
                    diag_errors.append("DATA_QUALITY_ONLY_STATE_MISMATCH")
                return self._error(
                    request, "INVALID_RESPONSE", "DEEPSEEK_INVALID_RESPONSE",
                    "DeepSeek response failed internal schema validation.",
                    details={"validation_errors": diag_errors},
                )
            return response
        except OpenAIAPITimeoutError:
            return self._error(
                request, "TIMEOUT", "DEEPSEEK_TIMEOUT", "DeepSeek request timed out.",
            )
        except OpenAIAPIConnectionError:
            return self._error(
                request, "AI_UNAVAILABLE", "DEEPSEEK_CONNECTION_ERROR",
                "DeepSeek service could not be reached.",
            )
        except OpenAIAPIStatusError as error:
            status_code = error.status_code
            details = self._status_error_details(error)
            if status_code == 400:
                return self._error(
                    request, "INVALID_REQUEST", "DEEPSEEK_BAD_REQUEST",
                    details.get("message", "DeepSeek rejected the request."), details,
                )
            if status_code == 401:
                return self._error(
                    request, "PROVIDER_ERROR", "DEEPSEEK_AUTHENTICATION_ERROR",
                    details.get("message", "DeepSeek authentication failed."), details,
                )
            if status_code == 402:
                return self._error(
                    request, "AI_UNAVAILABLE", "DEEPSEEK_INSUFFICIENT_BALANCE",
                    details.get("message", "DeepSeek account balance is insufficient."), details,
                )
            if status_code == 422:
                return self._error(
                    request, "INVALID_REQUEST", "DEEPSEEK_INVALID_PARAMETERS",
                    details.get("message", "DeepSeek request parameters are invalid."), details,
                )
            if status_code == 429:
                return self._error(
                    request, "AI_UNAVAILABLE", "DEEPSEEK_RATE_LIMIT",
                    details.get("message", "DeepSeek rate limit is active."), details,
                )
            if status_code == 503:
                return self._error(
                    request, "AI_UNAVAILABLE", "DEEPSEEK_OVERLOADED",
                    details.get("message", "DeepSeek service is overloaded."), details,
                )
            if status_code >= 500:
                return self._error(
                    request, "PROVIDER_ERROR", "DEEPSEEK_SERVER_ERROR",
                    details.get("message", "DeepSeek server error."), details,
                )
            return self._error(
                request, "PROVIDER_ERROR", "DEEPSEEK_API_ERROR",
                details.get("message", "DeepSeek API returned an unexpected status."), details,
            )
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError, IndexError) as exc:
            diag_details = {
                "diagnostic_stage": stage,
                "exception_type": type(exc).__name__,
            }
            if isinstance(exc, json.JSONDecodeError):
                diag_details["json_error_position"] = {
                    "line": exc.lineno,
                    "column": exc.colno,
                    "char_offset": exc.pos,
                }
            return self._error(
                request, "INVALID_RESPONSE", "DEEPSEEK_INVALID_RESPONSE",
                "DeepSeek returned an invalid structured response.",
                details=diag_details,
            )
        except Exception:
            return self._error(
                request, "PROVIDER_ERROR", "DEEPSEEK_UNKNOWN_ERROR",
                "DeepSeek transport returned an unexpected error.",
            )


def compare_provider_results(provider_results):
    """Summarize objective cross-provider differences without selecting a winner."""
    results = [value for value in provider_results if isinstance(value, dict)]
    provider_names = [value.get("provider") for value in results]
    provider_statuses = {
        provider: value.get("analysis_status")
        for provider, value in zip(provider_names, results)
        if isinstance(provider, str)
    }
    decision_states = {
        provider: value.get("decision_state")
        for provider, value in zip(provider_names, results)
        if isinstance(provider, str)
    }
    confidence = {
        provider: value.get("confidence")
        for provider, value in zip(provider_names, results)
        if isinstance(provider, str)
    }
    confidence_values = list(confidence.values())
    confidence["absolute_gap"] = (
        abs(confidence_values[0] - confidence_values[1])
        if len(confidence_values) == 2
        and all(isinstance(value, int) and not isinstance(value, bool)
                for value in confidence_values)
        else None
    )

    timeframe_agreement = {}
    for timeframe in ("daily", "hourly", "15m", "overall"):
        values = [
            value.get("timeframe_view", {}).get(timeframe)
            if isinstance(value.get("timeframe_view"), dict) else None
            for value in results
        ]
        timeframe_agreement[timeframe] = (
            len(values) == 2 and values[0] == values[1]
        )

    risk_flag_sets = [
        set(value.get("risk_flags", []))
        if isinstance(value.get("risk_flags"), list) else set()
        for value in results
    ]
    risk_flag_overlap = (
        sorted(risk_flag_sets[0] & risk_flag_sets[1])
        if len(risk_flag_sets) == 2 else []
    )
    decision_values = list(decision_states.values())
    decision_agreement = (
        len(decision_values) == 2 and decision_values[0] == decision_values[1]
    )
    provider_failure = (
        len(results) != 2
        or any(status not in ("OK", "DATA_QUALITY_ONLY")
               for status in provider_statuses.values())
    )
    confidence_agreement = (
        len(confidence_values) == 2 and confidence_values[0] == confidence_values[1]
    )
    risk_flags_agreement = (
        len(risk_flag_sets) == 2 and risk_flag_sets[0] == risk_flag_sets[1]
    )
    if provider_failure:
        classification = "PROVIDER_FAILURE"
    elif not decision_agreement:
        classification = "DECISION_DISAGREEMENT"
    elif (all(timeframe_agreement.values())
          and confidence_agreement and risk_flags_agreement):
        classification = "FULL_AGREEMENT"
    else:
        classification = "PARTIAL_AGREEMENT"

    return {
        "classification": classification,
        "decision_agreement": decision_agreement,
        "decision_states": decision_states,
        "confidence": confidence,
        "timeframe_agreement": timeframe_agreement,
        "risk_flag_overlap": risk_flag_overlap,
        "provider_statuses": provider_statuses,
    }


def _run_mock_adapter(adapter, request):
    try:
        response = adapter.analyze(copy.deepcopy(request))
    except TimeoutError as error:
        response = _error_ai_response(
            request, adapter.provider_name, "TIMEOUT", "ADAPTER_TIMEOUT", str(error),
        )
    except Exception as error:
        response = _error_ai_response(
            request, adapter.provider_name, "PROVIDER_ERROR", "ADAPTER_ERROR", str(error),
        )
    validation = validate_ai_response(response)
    if (not validation["ok"]
            or response.get("request_id") != request.get("request_id")
            or response.get("provider") != adapter.provider_name):
        return _error_ai_response(
            request, adapter.provider_name, "INVALID_RESPONSE", "INVALID_RESPONSE",
            "; ".join(validation["errors"]) or "Response identity mismatch.",
        )
    return response


def route_ai_requests(ai_requests, mode="PRIMARY", adapters=None, execution_profile="MOCK"):
    """Route common requests through explicitly selected mock or real adapters."""
    if mode not in ("PRIMARY", "FALLBACK", "COMPARE"):
        return {"ok": False, "status": "INVALID_ROUTER_MODE"}
    if execution_profile not in ("MOCK", "REAL"):
        return {"ok": False, "status": "INVALID_EXECUTION_PROFILE"}
    if not isinstance(ai_requests, list):
        return {"ok": False, "status": "INVALID_REQUESTS"}
    if adapters is None:
        if execution_profile == "MOCK":
            adapters = {
                "CLAUDE": ClaudeMockAdapter(),
                "DEEPSEEK": DeepSeekMockAdapter(),
            }
        else:
            adapters = {
                "CLAUDE": ClaudeRealAdapter(),
                "DEEPSEEK": DeepSeekRealAdapter(),
            }
    if (not isinstance(adapters, dict)
            or not isinstance(adapters.get("CLAUDE"), AIModelAdapter)
            or not isinstance(adapters.get("DEEPSEEK"), AIModelAdapter)):
        return {"ok": False, "status": "INVALID_ADAPTERS"}

    results = []
    for request in sorted(
        ai_requests,
        key=lambda value: (
            value.get("symbol", "") if isinstance(value, dict) else "",
            value.get("request_id", "") if isinstance(value, dict) else "",
        ),
    ):
        request_validation = validate_ai_request(request)
        providers_attempted = []
        fallback_used = False
        effective_provider = None
        comparison = None
        if not request_validation["ok"]:
            provider_results = [_error_ai_response(
                request, "CLAUDE", "INVALID_REQUEST", "INVALID_REQUEST",
                "; ".join(request_validation["errors"]),
            )]
        elif mode == "PRIMARY":
            providers_attempted.append("CLAUDE")
            provider_results = [_run_mock_adapter(adapters["CLAUDE"], request)]
            if provider_results[0]["analysis_status"] in ("OK", "DATA_QUALITY_ONLY"):
                effective_provider = "CLAUDE"
        elif mode == "FALLBACK":
            providers_attempted.append("CLAUDE")
            primary = _run_mock_adapter(adapters["CLAUDE"], request)
            provider_results = [primary]
            if primary["analysis_status"] in FALLBACK_ELIGIBLE_STATUSES:
                fallback_used = True
                providers_attempted.append("DEEPSEEK")
                provider_results.append(_run_mock_adapter(adapters["DEEPSEEK"], request))
            if primary["analysis_status"] in ("OK", "DATA_QUALITY_ONLY"):
                effective_provider = "CLAUDE"
            elif (len(provider_results) == 2
                  and provider_results[1]["analysis_status"] in ("OK", "DATA_QUALITY_ONLY")):
                effective_provider = "DEEPSEEK"
        else:
            providers_attempted.extend(("CLAUDE", "DEEPSEEK"))
            provider_results = [
                _run_mock_adapter(adapters["CLAUDE"], request),
                _run_mock_adapter(adapters["DEEPSEEK"], request),
            ]
            comparison = compare_provider_results(provider_results)
        providers_succeeded = [
            value["provider"] for value in provider_results
            if value["analysis_status"] in ("OK", "DATA_QUALITY_ONLY")
        ]
        results.append({
            "symbol": request.get("symbol") if isinstance(request, dict) else None,
            "request_id": request.get("request_id") if isinstance(request, dict) else None,
            "provider_results": provider_results,
            "provider_call_count": len(providers_attempted),
            "providers_attempted": providers_attempted,
            "providers_succeeded": providers_succeeded,
            "fallback_used": fallback_used,
            "effective_provider": effective_provider,
            "comparison": comparison,
        })
    provider_call_count = sum(value["provider_call_count"] for value in results)
    providers_attempted = list(dict.fromkeys(
        provider for value in results for provider in value["providers_attempted"]
    ))
    providers_succeeded = list(dict.fromkeys(
        provider for value in results for provider in value["providers_succeeded"]
    ))
    return clean_json_value({
        "ok": True,
        "mode": mode,
        "execution_profile": execution_profile,
        "request_count": len(ai_requests),
        "result_count": len(results),
        "provider_call_count": provider_call_count,
        "providers_attempted": providers_attempted,
        "providers_succeeded": providers_succeeded,
        "results": results,
    })


def _ai_plan_contains_sensitive_field(value):
    """Reject secrets and account identifiers before they enter an AI plan."""
    forbidden = {
        "account_id", "accountid", "acc_id", "accid",
        "api_key", "apikey", "authorization", "cookie",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in forbidden or _ai_plan_contains_sensitive_field(item):
                return True
    elif isinstance(value, list):
        return any(_ai_plan_contains_sensitive_field(item) for item in value)
    return False


def build_live_position_ai_execution_plan(invocation_result, analysis_state):
    """Build a deterministic, non-executing AI plan for current positions."""
    generated_at = (
        analysis_state.get("snapshot_time")
        if isinstance(analysis_state, dict) else None
    )

    def result(eligible=False, reason="INVOCATION_GATE_CLOSED", **values):
        requests = values.pop("requests", [])
        return clean_json_value({
            "schema_version": AI_EXECUTION_PLAN_SCHEMA_VERSION,
            "generated_at": generated_at,
            "eligible": eligible,
            "reason": reason,
            "monitor_scope": LIVE_POSITION_MONITOR_SCOPE,
            "symbols": [request["symbol"] for request in requests],
            "requests": requests,
            "recommended_mode": "PRIMARY" if eligible else None,
            "requires_explicit_execution": True,
            "data_quality_only": bool(requests) and all(
                request.get("analysis_mode") == "DATA_QUALITY_ONLY"
                for request in requests
            ),
            "network_calls_planned": len(requests),
            **values,
        })

    if (not isinstance(invocation_result, dict)
            or not isinstance(analysis_state, dict)
            or not isinstance(analysis_state.get("analysis_state"), dict)
            or not isinstance(generated_at, str)
            or not generated_at):
        return result(reason="INVALID_ORCHESTRATOR_INPUT")

    gate = invocation_result.get("ai_gate", invocation_result)
    if not isinstance(gate, dict) or gate.get("ok") is False:
        return result(reason="INVALID_INVOCATION_RESULT")
    if gate.get("should_invoke_ai") is not True:
        return result()
    invocation_requests = gate.get("requests")
    if not isinstance(invocation_requests, list) or not invocation_requests:
        return result(reason="INVALID_INVOCATION_RESULT")

    current_symbols = set(analysis_state["analysis_state"])
    requests = []
    rejected_non_positions = False
    for invocation_request in sorted(
        invocation_requests,
        key=lambda value: value.get("symbol", "") if isinstance(value, dict) else "",
    ):
        symbol = (
            invocation_request.get("symbol")
            if isinstance(invocation_request, dict) else None
        )
        if symbol not in current_symbols:
            rejected_non_positions = True
            continue
        request = build_ai_analysis_request(invocation_request, analysis_state)
        if request.get("ok") is False:
            return result(reason="COMMON_AI_REQUEST_BUILD_FAILED")
        if not validate_ai_request(request)["ok"]:
            return result(reason="INVALID_COMMON_AI_REQUEST")
        if _ai_plan_contains_sensitive_field(request):
            return result(reason="SENSITIVE_FIELD_REJECTED")
        requests.append(request)

    if not requests:
        return result(reason=(
            "NOT_CURRENT_POSITION"
            if rejected_non_positions else "NO_ELIGIBLE_REQUESTS"
        ))
    request_ids = [request["request_id"] for request in requests]
    if len(request_ids) != len(set(request_ids)):
        return result(reason="DUPLICATE_REQUEST_ID")
    return result(
        eligible=True,
        reason=(
            "PARTIAL_NOT_CURRENT_POSITION"
            if rejected_non_positions else "READY"
        ),
        requests=requests,
    )


@mcp.tool()
def prepare_live_position_ai_analysis(invocation_result: dict, analysis_state: dict):
    """Prepare a current-position AI plan without making network calls."""
    return build_live_position_ai_execution_plan(invocation_result, analysis_state)


@mcp.tool()
def execute_live_position_ai_plan(ai_execution_plan: dict, mode: str = "PRIMARY"):
    """Explicitly execute a previously prepared current-position AI plan."""
    if not isinstance(ai_execution_plan, dict):
        return {"ok": False, "status": "INVALID_AI_EXECUTION_PLAN"}
    requests = ai_execution_plan.get("requests")
    symbols = ai_execution_plan.get("symbols")
    if (ai_execution_plan.get("schema_version") != AI_EXECUTION_PLAN_SCHEMA_VERSION
            or ai_execution_plan.get("eligible") is not True
            or ai_execution_plan.get("monitor_scope") != LIVE_POSITION_MONITOR_SCOPE
            or ai_execution_plan.get("requires_explicit_execution") is not True
            or ai_execution_plan.get("recommended_mode") != "PRIMARY"
            or not isinstance(requests, list)
            or not requests
            or symbols != [request.get("symbol") for request in requests]
            or ai_execution_plan.get("network_calls_planned") != len(requests)
            or any(not validate_ai_request(request)["ok"] for request in requests)
            or _ai_plan_contains_sensitive_field(requests)):
        return {"ok": False, "status": "INVALID_AI_EXECUTION_PLAN"}
    return route_ai_requests(requests, mode=mode, execution_profile="REAL")


def build_market_regime_state(market_input):
    """Build a deterministic US market regime from one normalized QQQ proxy."""
    permissions = {
        "RISK_ON": "FULL",
        "SELECTIVE_RISK_ON": "SELECTIVE",
        "NEUTRAL": "LIMITED",
        "RISK_OFF": "DEFENSIVE",
        "INDETERMINATE": "UNKNOWN",
    }
    empty_factors = {
        "trend": {
            "status": "UNKNOWN", "score": 0,
            "evidence": {}, "availability": "UNAVAILABLE",
        },
        "momentum": {
            "status": "UNKNOWN", "score": 0,
            "evidence": {}, "availability": "UNAVAILABLE",
        },
        "breadth": {
            "status": "UNKNOWN", "score": 0,
            "evidence": {"source": None}, "availability": "UNAVAILABLE",
        },
        "stress": {
            "status": "UNKNOWN", "score": 0,
            "evidence": {"source": None}, "availability": "UNAVAILABLE",
        },
        "data_quality": {
            "status": "UNKNOWN", "score": 0,
            "evidence": {}, "availability": "UNAVAILABLE",
        },
    }

    generated_at = (
        market_input.get("generated_at")
        if isinstance(market_input, dict)
        and isinstance(market_input.get("generated_at"), str)
        else None
    )
    proxies = (
        market_input.get("proxies")
        if isinstance(market_input, dict) else None
    )
    proxy = proxies.get(MARKET_REGIME_PROXY) if isinstance(proxies, dict) else None
    proxy_names = [MARKET_REGIME_PROXY] if isinstance(proxy, dict) else []

    def result(regime="INDETERMINATE", score=0, confidence="LOW",
               factors=None, data_health=None, reason_codes=None):
        return clean_json_value({
            "schema_version": MARKET_REGIME_SCHEMA_VERSION,
            "generated_at": generated_at,
            "market": "US",
            "regime": regime,
            "attack_permission": permissions[regime],
            "score": score,
            "confidence": confidence,
            "factors": factors if factors is not None else empty_factors,
            "proxies": proxy_names,
            "data_health": data_health if isinstance(data_health, dict) else {
                "status": None,
            },
            "reason_codes": sorted(set(reason_codes or [])),
        })

    if (not isinstance(market_input, dict)
            or market_input.get("market") != "US"
            or generated_at is None
            or not isinstance(proxy, dict)):
        return result(reason_codes=[
            "BREADTH_UNAVAILABLE", "INSUFFICIENT_PROXY_DATA",
            "STRESS_DATA_UNAVAILABLE",
        ])

    data_health = proxy.get("data_health")
    health_status = (
        data_health.get("status") if isinstance(data_health, dict) else None
    )
    factors = copy.deepcopy(empty_factors)
    factors["data_quality"] = {
        "status": "OK" if health_status == "OK" else "LIMITED",
        "score": 0,
        "evidence": {"authoritative_status": health_status},
        "availability": "AVAILABLE" if isinstance(health_status, str) else "UNAVAILABLE",
    }
    base_reasons = ["BREADTH_UNAVAILABLE", "STRESS_DATA_UNAVAILABLE"]
    if health_status != "OK":
        return result(
            factors=factors,
            data_health=clean_json_value(data_health),
            reason_codes=base_reasons + ["DATA_HEALTH_LIMITED"],
        )

    timeframe = proxy.get("timeframe_state")
    allowed_states = {"BULLISH", "NEUTRAL", "BEARISH"}
    if not isinstance(timeframe, dict):
        return result(
            factors=factors,
            data_health=clean_json_value(data_health),
            reason_codes=base_reasons + ["TIMEFRAME_DATA_INSUFFICIENT"],
        )
    states = {}
    for name in ("daily", "hourly", "15m"):
        value = timeframe.get(name)
        state = value.get("state") if isinstance(value, dict) else None
        if state not in allowed_states:
            return result(
                factors=factors,
                data_health=clean_json_value(data_health),
                reason_codes=base_reasons + ["TIMEFRAME_DATA_INSUFFICIENT"],
            )
        states[name] = state

    daily = states["daily"]
    hourly = states["hourly"]
    short_term = states["15m"]
    overall = timeframe.get("overall")
    trend_score = 2 if daily == "BULLISH" else -2 if daily == "BEARISH" else 0
    trend_status = (
        "POSITIVE" if trend_score > 0 else
        "NEGATIVE" if trend_score < 0 else "MIXED"
    )
    factors["trend"] = {
        "status": trend_status,
        "score": trend_score,
        "evidence": {"daily_state": daily, "overall_alignment": overall},
        "availability": "AVAILABLE",
    }

    directional = {
        "BULLISH": 1,
        "NEUTRAL": 0,
        "BEARISH": -1,
    }
    momentum_score = directional[hourly] + directional[short_term]
    momentum_status = (
        "POSITIVE" if momentum_score > 0 else
        "NEGATIVE" if momentum_score < 0 else "MIXED"
    )
    factors["momentum"] = {
        "status": momentum_status,
        "score": momentum_score,
        "evidence": {"hourly_state": hourly, "15m_state": short_term},
        "availability": "AVAILABLE",
    }

    score = trend_score + momentum_score
    regime = (
        "RISK_ON" if score >= 3 else
        "SELECTIVE_RISK_ON" if score >= 1 else
        "RISK_OFF" if score <= -3 else
        "NEUTRAL"
    )
    confidence = "HIGH" if abs(score) == 4 else "MEDIUM" if abs(score) >= 2 else "LOW"
    reasons = list(base_reasons)
    reasons.append({
        "BULLISH": "DAILY_TREND_POSITIVE",
        "NEUTRAL": "DAILY_TREND_NEUTRAL",
        "BEARISH": "DAILY_TREND_NEGATIVE",
    }[daily])
    reasons.append({
        "BULLISH": "HOURLY_MOMENTUM_POSITIVE",
        "NEUTRAL": "HOURLY_MOMENTUM_NEUTRAL",
        "BEARISH": "HOURLY_MOMENTUM_NEGATIVE",
    }[hourly])
    reasons.append({
        "BULLISH": "SHORT_TERM_MOMENTUM_POSITIVE",
        "NEUTRAL": "SHORT_TERM_MOMENTUM_NEUTRAL",
        "BEARISH": "SHORT_TERM_WEAKNESS",
    }[short_term])
    if daily == hourly == short_term:
        reasons.append("BROAD_MARKET_ALIGNMENT")
    else:
        reasons.append("MULTI_TIMEFRAME_MIXED")
    return result(
        regime=regime,
        score=score,
        confidence=confidence,
        factors=factors,
        data_health=clean_json_value(data_health),
        reason_codes=reasons,
    )


@mcp.tool()
def get_market_regime_snapshot(count: int = 100):
    """Read QQQ bars and return a deterministic US market regime snapshot."""
    bar_count = max(count, 100) if isinstance(count, int) and count > 0 else count
    bars = {
        "daily": get_bars(MARKET_REGIME_PROXY, timeframe="1d", count=bar_count),
        "hourly": get_bars(MARKET_REGIME_PROXY, timeframe="1h", count=bar_count),
        "15m": get_bars(MARKET_REGIME_PROXY, timeframe="15m", count=bar_count),
    }
    timeframe_state = {}
    latest_times = {}
    for name, value in bars.items():
        rows = value.get("data") if isinstance(value, dict) else None
        source_ok = value.get("ok") is True and isinstance(rows, list) and bool(rows)
        latest_times[name] = rows[-1].get("time_key") if source_ok else None
        indicators = calculate_indicators_from_bars(rows if source_ok else [])
        timeframe_state[name] = summarize_timeframe_state(indicators)
    timeframe_state["overall"] = summarize_timeframe_alignment(timeframe_state)

    health = data_health_check(MARKET_REGIME_PROXY, timeframe="15m")
    health_status = (
        health.get("status") if isinstance(health, dict) else "DATA_UNAVAILABLE"
    )
    market_input = {
        "generated_at": datetime.now().isoformat(),
        "market": "US",
        "proxies": {
            MARKET_REGIME_PROXY: {
                "timeframe_state": timeframe_state,
                "data_health": {
                    "status": health_status,
                    "latest_times": latest_times,
                    "reason_codes": (
                        health.get("reason_codes", [])
                        if isinstance(health, dict) else []
                    ),
                    "authority": "data_health_check",
                },
            },
        },
    }
    return build_market_regime_state(market_input)




def _rs_window_diff_pp(target_closes, benchmark_closes, window):
    """Relative performance over the last `window` bars, in percentage points.

    Defined exactly as target_period_return - benchmark_period_return.
    Returns None when either series has fewer than window + 1 closes or a
    period endpoint is not a finite, positive price.
    """
    if len(target_closes) < window + 1 or len(benchmark_closes) < window + 1:
        return None
    endpoints = (
        target_closes[-1], target_closes[-1 - window],
        benchmark_closes[-1], benchmark_closes[-1 - window],
    )
    if any(not math.isfinite(value) or value <= 0 for value in endpoints):
        return None
    target_return = (target_closes[-1] / target_closes[-1 - window] - 1.0) * 100.0
    benchmark_return = (
        benchmark_closes[-1] / benchmark_closes[-1 - window] - 1.0
    ) * 100.0
    return target_return - benchmark_return


def _rs_ratio_series(target_closes, benchmark_closes):
    """Relative ratio series target_close / benchmark_close.

    A non-positive or non-finite close yields None (never fake a ratio).
    """
    ratio = []
    for target_close, benchmark_close in zip(target_closes, benchmark_closes):
        if (not math.isfinite(target_close) or not math.isfinite(benchmark_close)
                or target_close <= 0 or benchmark_close <= 0):
            ratio.append(None)
        else:
            ratio.append(target_close / benchmark_close)
    return ratio


def _rs_sma(values, window):
    """SMA over the last `window` values; None when insufficient or invalid."""
    tail = values[-window:]
    if len(tail) < window or any(value is None for value in tail):
        return None
    return sum(tail) / window


def _rs_relative_direction(ratio):
    """Improvement / deterioration of the relative series.

    Compares the recent 5-bar average ratio against the 20-bar average that
    ends 5 bars ago, so a rising relative series is IMPROVING even when the
    absolute level is still underperforming (and vice versa). Deadband 0.5pp.
    Requires at least 25 ratio points; otherwise UNKNOWN.
    """
    if len(ratio) < 25:
        return "UNKNOWN", {}
    recent = _rs_sma(ratio, 5)
    prior = _rs_sma(ratio[:-5], 20)
    if recent is None or prior is None or prior == 0:
        return "UNKNOWN", {}
    change_pp = (recent / prior - 1.0) * 100.0
    boundary_tolerance = 1e-12
    if (change_pp > 0.5
            and not math.isclose(
                change_pp, 0.5, rel_tol=0.0, abs_tol=boundary_tolerance)):
        direction = "IMPROVING"
    elif (change_pp < -0.5
          and not math.isclose(
              change_pp, -0.5, rel_tol=0.0,
              abs_tol=boundary_tolerance)):
        direction = "DETERIORATING"
    else:
        direction = "STABLE"
    return direction, {
        "recent_ratio_sma5": round(recent, 6),
        "prior_ratio_sma20": round(prior, 6),
        "change_pp": round(change_pp, 6),
        "deadband_pp": 0.5,
    }


def _rs_timeframe(
    target_rows,
    benchmark_rows,
    target_health,
    benchmark_health,
    return_window,
    trend_window,
    momentum_window,
    persistence_windows,
    return_threshold,
    momentum_deadband,
    minimum_bars,
):
    """One timeframe of deterministic Relative Strength.

    Aligns target and benchmark bars by inner join on time_key (never by row
    number), then scores four transparent factors on the aligned closes:
    relative_return (+1/0/-1 vs a return threshold), relative_trend (last
    ratio vs its MA), relative_momentum (short-window relative change vs a
    deadband), persistence (sign agreement across persistence windows).
    Unified Data Health gates the timeframe: any non-OK target or benchmark
    health makes this timeframe INDETERMINATE.
    """
    factors_empty = {
        "relative_return": {
            "status": "UNKNOWN", "score": 0, "evidence": {},
            "availability": "UNAVAILABLE",
        },
        "relative_trend": {
            "status": "UNKNOWN", "score": 0, "evidence": {},
            "availability": "UNAVAILABLE",
        },
        "relative_momentum": {
            "status": "UNKNOWN", "score": 0, "evidence": {},
            "availability": "UNAVAILABLE",
        },
        "persistence": {
            "status": "UNKNOWN", "score": 0, "evidence": {},
            "availability": "UNAVAILABLE",
        },
    }
    result = {
        "state": "INDETERMINATE",
        "score": 0,
        "factors": factors_empty,
        "aligned_bar_count": 0,
        "latest": {"target": None, "benchmark": None, "aligned": None},
        "reason_codes": [],
    }

    def align(rows):
        return _dedupe_bars_by_time(rows)

    target_map, target_conflict = align(target_rows)
    benchmark_map, benchmark_conflict = align(benchmark_rows)
    common = sorted(set(target_map) & set(benchmark_map))
    result["aligned_bar_count"] = len(common)
    if target_map:
        result["latest"]["target"] = max(target_map)
    if benchmark_map:
        result["latest"]["benchmark"] = max(benchmark_map)
    if common:
        result["latest"]["aligned"] = common[-1]

    if target_conflict or benchmark_conflict:
        result["reason_codes"].append("CONFLICTING_DUPLICATE_TIMESTAMP")
        return result

    if target_health != "OK":
        result["reason_codes"].append("TARGET_DATA_HEALTH_LIMITED")
        return result
    if benchmark_health != "OK":
        result["reason_codes"].append("BENCHMARK_DATA_HEALTH_LIMITED")
        return result

    if len(common) < minimum_bars:
        result["reason_codes"].append("INSUFFICIENT_ALIGNED_BARS")
        return result

    target_closes = [target_map[key] for key in common]
    benchmark_closes = [benchmark_map[key] for key in common]
    longest_window = max(
        return_window, trend_window, momentum_window, *persistence_windows)
    required_target = target_closes[-longest_window - 1:]
    required_benchmark = benchmark_closes[-longest_window - 1:]
    if (any(value <= 0 for value in required_target)
            or any(value <= 0 for value in required_benchmark)):
        result["reason_codes"].append("INSUFFICIENT_ALIGNED_BARS")
        return result
    ratio = _rs_ratio_series(target_closes, benchmark_closes)

    factors = {
        "relative_return": {
            "status": "UNKNOWN", "score": 0, "evidence": {},
            "availability": "UNAVAILABLE",
        },
        "relative_trend": {
            "status": "UNKNOWN", "score": 0, "evidence": {},
            "availability": "UNAVAILABLE",
        },
        "relative_momentum": {
            "status": "UNKNOWN", "score": 0, "evidence": {},
            "availability": "UNAVAILABLE",
        },
        "persistence": {
            "status": "UNKNOWN", "score": 0, "evidence": {},
            "availability": "UNAVAILABLE",
        },
    }

    return_diff = _rs_window_diff_pp(
        target_closes, benchmark_closes, return_window)
    if return_diff is None:
        result["reason_codes"].append("INSUFFICIENT_ALIGNED_BARS")
        return result
    factors["relative_return"].update({
        "availability": "AVAILABLE",
        "evidence": {
            "window": return_window,
            "relative_return_pp": round(return_diff, 6),
            "threshold_pp": return_threshold,
        },
    })
    if return_diff > return_threshold:
        factors["relative_return"].update({"status": "POSITIVE", "score": 1})
    elif return_diff < -return_threshold:
        factors["relative_return"].update({"status": "NEGATIVE", "score": -1})
    else:
        factors["relative_return"].update({"status": "NEUTRAL"})

    ratio_ma = _rs_sma(ratio, trend_window)
    if ratio_ma is None or ratio[-1] is None:
        result["reason_codes"].append("INSUFFICIENT_ALIGNED_BARS")
        return result
    factors["relative_trend"].update({
        "availability": "AVAILABLE",
        "evidence": {
            "window": trend_window,
            "last_ratio": round(ratio[-1], 6),
            "ratio_ma": round(ratio_ma, 6),
        },
    })
    if ratio[-1] > ratio_ma:
        factors["relative_trend"].update({"status": "POSITIVE", "score": 1})
    elif ratio[-1] < ratio_ma:
        factors["relative_trend"].update({"status": "NEGATIVE", "score": -1})
    else:
        factors["relative_trend"].update({"status": "NEUTRAL"})

    momentum_diff = _rs_window_diff_pp(
        target_closes, benchmark_closes, momentum_window)
    if momentum_diff is None:
        result["reason_codes"].append("INSUFFICIENT_ALIGNED_BARS")
        return result
    factors["relative_momentum"].update({
        "availability": "AVAILABLE",
        "evidence": {
            "window": momentum_window,
            "relative_change_pp": round(momentum_diff, 6),
            "deadband_pp": momentum_deadband,
        },
    })
    if momentum_diff > momentum_deadband:
        factors["relative_momentum"].update({"status": "POSITIVE", "score": 1})
    elif momentum_diff < -momentum_deadband:
        factors["relative_momentum"].update({"status": "NEGATIVE", "score": -1})
    else:
        factors["relative_momentum"].update({"status": "NEUTRAL"})

    window_diffs = {}
    for window in persistence_windows:
        window_diffs[window] = _rs_window_diff_pp(
            target_closes, benchmark_closes, window)
    available_diffs = [value for value in window_diffs.values()
                       if value is not None]
    factors["persistence"]["evidence"] = {
        "windows": {
            str(window): (round(value, 6) if value is not None else None)
            for window, value in window_diffs.items()
        },
        "minimum_windows": 2,
    }
    if len(available_diffs) >= 2:
        factors["persistence"]["availability"] = "AVAILABLE"
        if all(value > 0 for value in available_diffs):
            factors["persistence"].update({"status": "POSITIVE", "score": 1})
        elif all(value < 0 for value in available_diffs):
            factors["persistence"].update({"status": "NEGATIVE", "score": -1})
        else:
            factors["persistence"].update({"status": "MIXED"})

    if any(factor["availability"] != "AVAILABLE"
           for factor in factors.values()):
        result["reason_codes"].append("INSUFFICIENT_ALIGNED_BARS")
        return result

    score = sum(factor["score"] for factor in factors.values())
    state = (
        "STRONG_OUTPERFORM" if score >= 3 else
        "OUTPERFORM" if score >= 1 else
        "STRONG_UNDERPERFORM" if score <= -3 else
        "UNDERPERFORM" if score <= -1 else
        "NEUTRAL"
    )
    result.update({"state": state, "score": score, "factors": factors})
    return result


def build_relative_strength_state(rs_input):
    """Deterministic Relative Strength state vs a broad benchmark proxy.

    Pure function: consumes aligned bars plus Unified Data Health statuses.
    Daily is the primary timeframe, 1H confirms, 15m contributes only light
    short-term confirmation (overall aggregation ratio 4:2:1). Market Regime
    is deliberately not an input to this function; RS and Regime stay
    orthogonal. No positions, no AI, no runtime state, no trading semantics.
    """
    generated_at = None
    symbol = None
    benchmark = None

    def result(state="INDETERMINATE", score=0, relative_direction="UNKNOWN",
               confidence="LOW", timeframes=None, factors=None,
               aligned_bar_counts=None, data_health=None,
               relative_direction_evidence=None, reason_codes=None):
        return clean_json_value({
            "schema_version": RELATIVE_STRENGTH_SCHEMA_VERSION,
            "generated_at": generated_at,
            "symbol": symbol,
            "benchmark": benchmark,
            "state": state,
            "relative_direction": relative_direction,
            "score": score,
            "confidence": confidence,
            "timeframes": timeframes if timeframes is not None else {},
            "factors": factors if factors is not None else {},
            "aligned_bar_counts": aligned_bar_counts
            if aligned_bar_counts is not None else {},
            "data_health": data_health if data_health is not None else {},
            "relative_direction_evidence": relative_direction_evidence
            if relative_direction_evidence is not None else {},
            "reason_codes": sorted(set(reason_codes or [])),
        })

    if not isinstance(rs_input, dict):
        return result(reason_codes=["INVALID_RS_INPUT"])
    symbol = rs_input.get("symbol")
    benchmark = rs_input.get("benchmark")
    generated_at = rs_input.get("generated_at")
    if (not isinstance(symbol, str) or not symbol
            or not isinstance(benchmark, str) or not benchmark
            or not isinstance(generated_at, str) or not generated_at):
        return result(reason_codes=["INVALID_RS_INPUT"])
    bars = rs_input.get("bars")
    data_health = rs_input.get("data_health")
    if not isinstance(bars, dict) or not isinstance(data_health, dict):
        return result(reason_codes=["INVALID_RS_INPUT"])

    target_bars = (
        bars.get("target") if isinstance(bars.get("target"), dict) else {})
    benchmark_bars = (
        bars.get("benchmark") if isinstance(bars.get("benchmark"), dict)
        else {})
    target_health = (
        data_health.get("target")
        if isinstance(data_health.get("target"), dict) else {})
    benchmark_health = (
        data_health.get("benchmark")
        if isinstance(data_health.get("benchmark"), dict) else {})

    timeframe_specs = {
        "daily": {
            "return_window": 20, "trend_window": 20, "momentum_window": 5,
            "persistence_windows": (5, 20, 60), "return_threshold": 2.0,
            "momentum_deadband": 0.5, "minimum_bars": 21,
        },
        "hourly": {
            "return_window": 20, "trend_window": 20, "momentum_window": 5,
            "persistence_windows": (5, 20), "return_threshold": 1.0,
            "momentum_deadband": 0.25, "minimum_bars": 21,
        },
        "15m": {
            "return_window": 20, "trend_window": 20, "momentum_window": 5,
            "persistence_windows": (5, 20), "return_threshold": 0.5,
            "momentum_deadband": 0.15, "minimum_bars": 21,
        },
    }

    timeframes = {}
    aligned_bar_counts = {}
    for name, spec in timeframe_specs.items():
        timeframes[name] = _rs_timeframe(
            target_bars.get(name)
            if isinstance(target_bars.get(name), list) else [],
            benchmark_bars.get(name)
            if isinstance(benchmark_bars.get(name), list) else [],
            target_health.get(name),
            benchmark_health.get(name),
            return_window=spec["return_window"],
            trend_window=spec["trend_window"],
            momentum_window=spec["momentum_window"],
            persistence_windows=spec["persistence_windows"],
            return_threshold=spec["return_threshold"],
            momentum_deadband=spec["momentum_deadband"],
            minimum_bars=spec["minimum_bars"],
        )
        aligned_bar_counts[name] = timeframes[name]["aligned_bar_count"]

    daily = timeframes["daily"]
    hourly = timeframes["hourly"]
    short_term = timeframes["15m"]

    reasons = []
    for frame in timeframes.values():
        reasons.extend(frame["reason_codes"])

    data_health_out = {
        "target": target_health,
        "benchmark": benchmark_health,
    }

    if daily["state"] == "INDETERMINATE":
        reasons.append("DAILY_RS_INDETERMINATE")
        reasons.append("RELATIVE_DIRECTION_UNKNOWN")
        return result(
            timeframes=timeframes,
            aligned_bar_counts=aligned_bar_counts,
            data_health=data_health_out,
            reason_codes=reasons,
        )

    # Transparent aggregation: daily 4 : hourly 2 : 15m 1.
    hourly_contribution = int(hourly["score"] / 2)
    short_term_contribution = int(short_term["score"] / 3)
    intraday_score = hourly_contribution + short_term_contribution
    raw_score = daily["score"] + intraday_score
    # Daily is the directional anchor: intraday may neutralize, not reverse.
    if daily["score"] > 0 and raw_score < 0:
        raw_score = 0
    elif daily["score"] < 0 and raw_score > 0:
        raw_score = 0
    score = max(-4, min(4, raw_score))
    if score != raw_score:
        reasons.append("RS_SCORE_CLAMPED")

    state = (
        "STRONG_OUTPERFORM" if score >= 3 else
        "OUTPERFORM" if score >= 1 else
        "STRONG_UNDERPERFORM" if score <= -3 else
        "UNDERPERFORM" if score <= -1 else
        "NEUTRAL"
    )

    # Direction from the daily relative ratio slope (window-normalized).
    daily_target_closes = None
    daily_ratio = []
    target_map_daily = {}
    benchmark_map_daily = {}
    for row in (
        target_bars.get("daily")
        if isinstance(target_bars.get("daily"), list) else []
    ):
        if isinstance(row, dict) and row.get("time_key") is not None:
            try:
                value = float(row.get("close"))
            except (TypeError, ValueError, OverflowError):
                value = None
            if value is not None and math.isfinite(value):
                target_map_daily[str(row.get("time_key"))] = value
    for row in (
        benchmark_bars.get("daily")
        if isinstance(benchmark_bars.get("daily"), list) else []
    ):
        if isinstance(row, dict) and row.get("time_key") is not None:
            try:
                value = float(row.get("close"))
            except (TypeError, ValueError, OverflowError):
                value = None
            if value is not None and math.isfinite(value):
                benchmark_map_daily[str(row.get("time_key"))] = value
    common_daily = sorted(set(target_map_daily) & set(benchmark_map_daily))
    daily_ratio = _rs_ratio_series(
        [target_map_daily[key] for key in common_daily],
        [benchmark_map_daily[key] for key in common_daily],
    )
    relative_direction, direction_evidence = _rs_relative_direction(daily_ratio)
    reasons.append(f"RELATIVE_DIRECTION_{relative_direction}")

    # Deterministic reason codes (daily windows / trend / momentum /
    # intraday confirmations / self benchmark).
    persistence_evidence = daily["factors"]["persistence"]["evidence"]
    for window, code_positive, code_negative in (
        (5, "RELATIVE_5D_POSITIVE", "RELATIVE_5D_NEGATIVE"),
        (20, "RELATIVE_20D_POSITIVE", "RELATIVE_20D_NEGATIVE"),
        (60, "RELATIVE_60D_POSITIVE", "RELATIVE_60D_NEGATIVE"),
    ):
        value = persistence_evidence.get("windows", {}).get(str(window))
        if value is not None and value > 0:
            reasons.append(code_positive)
        elif value is not None and value < 0:
            reasons.append(code_negative)

    if daily["factors"]["relative_trend"]["score"] > 0:
        reasons.append("RELATIVE_TREND_ABOVE_MA")
    elif daily["factors"]["relative_trend"]["score"] < 0:
        reasons.append("RELATIVE_TREND_BELOW_MA")
    if daily["factors"]["relative_momentum"]["score"] > 0:
        reasons.append("RELATIVE_MOMENTUM_IMPROVING")
    elif daily["factors"]["relative_momentum"]["score"] < 0:
        reasons.append("RELATIVE_MOMENTUM_DETERIORATING")

    if hourly["state"] != "INDETERMINATE":
        reasons.append(
            "HOURLY_CONFIRMATION_POSITIVE" if hourly["score"] > 0 else
            "HOURLY_CONFIRMATION_NEGATIVE" if hourly["score"] < 0 else
            "HOURLY_CONFIRMATION_NEUTRAL")
    if short_term["state"] != "INDETERMINATE":
        reasons.append(
            "SHORT_TERM_RELATIVE_STRENGTH" if short_term["score"] > 0 else
            "SHORT_TERM_RELATIVE_WEAKNESS" if short_term["score"] < 0 else
            "SHORT_TERM_RELATIVE_NEUTRAL")
    if symbol == benchmark:
        reasons.append("SELF_BENCHMARK")

    # Coverage-aware confidence: bar counts and timeframe availability matter.
    daily_factors_available = sum(
        1 for factor in daily["factors"].values()
        if factor["availability"] == "AVAILABLE")
    intraday_available = [
        hourly["state"] != "INDETERMINATE",
        short_term["state"] != "INDETERMINATE",
    ]
    if (aligned_bar_counts["daily"] >= 61
            and daily_factors_available == 4
            and all(intraday_available)):
        confidence = "HIGH"
    elif daily_factors_available >= 3 and any(intraday_available):
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    factors = {}
    for name in ("relative_return", "relative_trend",
                 "relative_momentum", "persistence"):
        source = daily["factors"][name]
        factors[name] = {
            "status": source["status"],
            "score": source["score"],
            "evidence": dict(source["evidence"]),
            "availability": source["availability"],
        }
    factors["relative_return"]["evidence"]["hourly_20bar_diff_pp"] = (
        hourly["factors"]["relative_return"]["evidence"].get("relative_return_pp"))
    factors["relative_return"]["evidence"]["15m_20bar_diff_pp"] = (
        short_term["factors"]["relative_return"]["evidence"].get("relative_return_pp"))
    factors["intraday_confirmation"] = {
        "status": (
            "POSITIVE" if intraday_score > 0 else
            "NEGATIVE" if intraday_score < 0 else "NEUTRAL"),
        "score": intraday_score,
        "evidence": {
            "hourly_score": hourly["score"],
            "hourly_state": hourly["state"],
            "15m_score": short_term["score"],
            "15m_state": short_term["state"],
            "rule": "int(hourly_score / 2) + int(15m_score / 3)",
        },
        "availability": (
            "AVAILABLE" if any(intraday_available) else "UNAVAILABLE"),
    }

    return result(
        state=state,
        score=score,
        relative_direction=relative_direction,
        confidence=confidence,
        timeframes=timeframes,
        factors=factors,
        aligned_bar_counts=aligned_bar_counts,
        data_health=data_health_out,
        relative_direction_evidence=direction_evidence,
        reason_codes=reasons,
    )


@mcp.tool()
def get_relative_strength_snapshot(
    symbol: str,
    benchmark: str = RELATIVE_STRENGTH_DEFAULT_BENCHMARK,
    count: int = 300,
):
    """Read-only deterministic Relative Strength snapshot vs a benchmark.

    Fetches target and benchmark bars for Daily / 1H / 15m, consumes the
    Unified Data Health authority for every (symbol, timeframe) pair, and
    delegates all scoring to build_relative_strength_state. Does not read
    positions, write runtime state, call AI, or touch trading APIs.
    """
    bar_count = max(count, 120) if isinstance(count, int) and count > 0 else count
    bars = {"target": {}, "benchmark": {}}
    data_health = {"target": {}, "benchmark": {}}
    for key, value in (("target", symbol), ("benchmark", benchmark)):
        for name, timeframe in (("daily", "1d"), ("hourly", "1h"),
                                ("15m", "15m")):
            response = get_bars(value, timeframe=timeframe, count=bar_count)
            bars[key][name] = (
                response.get("data")
                if isinstance(response, dict) and response.get("ok") is True
                else []
            )
            health = data_health_check(value, timeframe=timeframe)
            data_health[key][name] = (
                health.get("status") if isinstance(health, dict)
                else "DATA_UNAVAILABLE"
            )
    return build_relative_strength_state({
        "generated_at": datetime.now().isoformat(),
        "symbol": symbol,
        "benchmark": benchmark,
        "bars": bars,
        "data_health": data_health,
    })














@mcp.tool()
def get_price_structure_snapshot(symbol: str, count: int = 300):
    """Read-only deterministic Price Structure snapshot.

    Fetches Daily / 1H / 15m bars and consumes the Unified Data Health
    authority per timeframe, then delegates all structure logic to
    build_price_structure_state. Does not read positions, write runtime
    state, call AI, or touch trading APIs.
    """
    bar_count = max(count, 120) if isinstance(count, int) and count > 0 else count
    bars = {}
    data_health = {}
    for name, timeframe in (("daily", "1d"), ("hourly", "1h"),
                            ("15m", "15m")):
        response = get_bars(symbol, timeframe=timeframe, count=bar_count)
        bars[name] = (
            response.get("data")
            if isinstance(response, dict) and response.get("ok") is True
            else []
        )
        health = data_health_check(symbol, timeframe=timeframe)
        data_health[name] = (
            health.get("status") if isinstance(health, dict)
            else "DATA_UNAVAILABLE"
        )
    return build_price_structure_state({
        "generated_at": datetime.now().isoformat(),
        "symbol": symbol,
        "bars": bars,
        "data_health": data_health,
    })

VWAP_SCHEMA_VERSION = 1
VWAP_AT_THRESHOLD_PCT = 0.20
VWAP_SLOPE_K = 3
VWAP_SLOPE_FLAT_PCT = 0.10
VWAP_PRICE_POSITIONS = ("ABOVE_VWAP", "AT_VWAP", "BELOW_VWAP", "INDETERMINATE")
VWAP_SLOPES = ("RISING", "FLAT", "FALLING", "UNKNOWN")
VWAP_SESSION_STATUSES = ("CURRENT_ACTIVE_SESSION", "CURRENT_COMPLETE_SESSION",
                         "PREVIOUS_COMPLETE_SESSION", "INDETERMINATE")
VWAP_REASON_CODES = (
    "CURRENT_ACTIVE_SESSION", "CURRENT_COMPLETE_SESSION",
    "PREVIOUS_COMPLETE_SESSION", "PRICE_ABOVE_VWAP", "PRICE_AT_VWAP",
    "PRICE_BELOW_VWAP", "VWAP_RISING", "VWAP_FLAT", "VWAP_FALLING",
    "INSUFFICIENT_SESSION_BARS", "ZERO_SESSION_VOLUME", "INVALID_PRICE_DATA",
    "INVALID_VOLUME_DATA", "CONFLICTING_DUPLICATE_TIMESTAMP",
    "DATA_HEALTH_LIMITED", "HALF_DAY_SESSION", "SESSION_NOT_AVAILABLE",
)


def _vwap_is_regular_bar_close(timestamp_text):
    """Futu 15m time_key semantics: BAR_CLOSE (empirically verified 2026-09-08).

    A regular-session bar ends in (09:30, 16:00] ET, i.e. 09:45..16:00
    inclusive; 26 bars per whole session. Bars ending <=09:30 (premarket) or
    >16:00 (after-hours) are excluded. Never guessed: see D4.1 test note.
    """
    if not isinstance(timestamp_text, str) or len(timestamp_text) < 16:
        return False
    try:
        hour = int(timestamp_text[11:13])
        minute = int(timestamp_text[14:16])
    except (ValueError, IndexError):
        return False
    minutes = hour * 60 + minute
    return 9 * 60 + 30 < minutes <= 16 * 60


def build_session_vwap_state(vwap_input):
    """Pure deterministic Session VWAP builder (15m session bars only).

    No Moomoo call, no runtime write, no AI, no account access. Does not
    read Market Regime / Relative Strength / Price Structure / positions.
    Session VWAP = sum(TP_i * vol_i) / sum(vol_i) over one regular session.
    Zero-volume bars keep their price but contribute nothing; negative /
    non-numeric volume or invalid prices mark the session INDETERMINATE.
    Reuses the shared duplicate policy (_dedupe_bars_by_time): identical
    duplicates dedupe; conflicting duplicates -> INDETERMINATE.
    """
    generated_at = None
    symbol = None
    if not isinstance(vwap_input, dict):
        vwap_input = {}
    generated_at = vwap_input.get("generated_at")
    symbol = vwap_input.get("symbol")

    def result(session_date=None, session_status="INDETERMINATE",
               session_vwap=None, current_close=None,
               distance_to_vwap_pct=None, price_position="INDETERMINATE",
               vwap_slope="UNKNOWN", bars_used=0, total_volume=0.0,
               recent_context=None, hourly_context="INDETERMINATE",
               data_health=None, confidence="INDETERMINATE",
               reason_codes=None):
        return clean_json_value({
            "schema_version": VWAP_SCHEMA_VERSION,
            "generated_at": generated_at,
            "symbol": symbol,
            "session_date": session_date,
            "session_status": session_status,
            "session_vwap": session_vwap,
            "current_close": current_close,
            "distance_to_vwap_pct": distance_to_vwap_pct,
            "price_position": price_position,
            "vwap_slope": vwap_slope,
            "bars_used": bars_used,
            "total_volume": total_volume,
            "recent_context": recent_context if recent_context is not None
            else {"window": 5, "bars_above_vwap": 0, "bars_below_vwap": 0},
            "hourly_context": hourly_context,
            "data_health": data_health if data_health is not None else {},
            "confidence": confidence,
            "reason_codes": sorted(set(reason_codes or [])),
        })

    bars = vwap_input.get("bars_15m") or []
    if not isinstance(bars, list):
        bars = []
    session_phase = vwap_input.get("session_phase")
    session_date = vwap_input.get("session_date")
    if not isinstance(session_date, str) or not session_date:
        session_date = None
    health = vwap_input.get("data_health") or {}
    health_ok = health.get("ok") is True and health.get("status") == "OK"
    date_type = health.get("expected_trading_date_type")
    hourly = vwap_input.get("hourly") or {}

    reasons = []
    if session_phase == "REGULAR":
        session_status = "CURRENT_ACTIVE_SESSION"
    elif session_phase == "AFTER_HOURS":
        session_status = "CURRENT_COMPLETE_SESSION"
    else:
        session_status = "PREVIOUS_COMPLETE_SESSION"
    reasons.append(session_status)
    if session_date is None:
        reasons.append("SESSION_NOT_AVAILABLE")
        return result(session_status=session_status, data_health=health,
                      confidence="INDETERMINATE", reason_codes=reasons)
    if not health_ok:
        reasons.append("DATA_HEALTH_LIMITED")
    if date_type == "HALF":
        reasons.append("HALF_DAY_SESSION")

    # ---- session bar selection (strict regular-hours filter) ----
    session_rows = []
    invalid_price = False
    invalid_volume = False
    for row in bars:
        if not isinstance(row, dict):
            continue
        time_key = row.get("time_key")
        if not isinstance(time_key, str) or not time_key.startswith(session_date):
            continue
        if not _vwap_is_regular_bar_close(time_key):
            continue
        session_rows.append(row)

    # bar validity (price / volume safety); None volume normalizes to 0.0 so
    # the shared dedupe helper keeps the bar instead of silently dropping it.
    normalized_rows = []
    for row in session_rows:
        try:
            high = float(row.get("high"))
            low = float(row.get("low"))
            close = float(row.get("close"))
        except (TypeError, ValueError, OverflowError):
            invalid_price = True
            continue
        if not all(math.isfinite(x) and x > 0 for x in (high, low, close)):
            invalid_price = True
            continue
        if high < low:
            invalid_price = True
            continue
        if close < low or close > high:
            invalid_price = True
            continue
        vol_raw = row.get("volume")
        if vol_raw is None:
            volume = 0.0
        else:
            try:
                volume = float(vol_raw)
            except (TypeError, ValueError, OverflowError):
                invalid_volume = True
                continue
            if not math.isfinite(volume) or volume < 0:
                invalid_volume = True
                continue
        normalized_rows.append({
            "time_key": str(row.get("time_key")),
            "high": high, "low": low, "close": close, "volume": volume,
        })

    if invalid_price:
        reasons.append("INVALID_PRICE_DATA")
        return result(session_date=session_date, session_status=session_status,
                      data_health=health, confidence="INDETERMINATE",
                      reason_codes=reasons)
    if invalid_volume:
        reasons.append("INVALID_VOLUME_DATA")
        return result(session_date=session_date, session_status=session_status,
                      data_health=health, confidence="INDETERMINATE",
                      reason_codes=reasons)

    # shared duplicate policy (never first/last wins)
    mapping, conflicting = _dedupe_bars_by_time(
        normalized_rows, fields=("high", "low", "close", "volume"))
    if conflicting:
        reasons.append("CONFLICTING_DUPLICATE_TIMESTAMP")
        return result(session_date=session_date, session_status=session_status,
                      data_health=health, confidence="INDETERMINATE",
                      reason_codes=reasons)
    # deterministic order + dedupe via mapping membership
    ordered_keys = sorted(mapping)
    rows = []
    for key in ordered_keys:
        hh, ll, cc, vv = mapping[key]
        rows.append((key, hh, ll, cc, vv))

    bars_used = len(rows)
    total_volume = sum(row[4] for row in rows)
    if bars_used < 2:
        reasons.append("INSUFFICIENT_SESSION_BARS")
        return result(session_date=session_date, session_status=session_status,
                      bars_used=bars_used, total_volume=total_volume,
                      data_health=health, confidence="INDETERMINATE",
                      reason_codes=reasons)
    if total_volume <= 0:
        reasons.append("ZERO_SESSION_VOLUME")
        return result(session_date=session_date, session_status=session_status,
                      bars_used=bars_used, total_volume=total_volume,
                      data_health=health, confidence="INDETERMINATE",
                      reason_codes=reasons)

    # ---- cumulative session VWAP ----
    vwap_series = []
    cum_pv = 0.0
    cum_v = 0.0
    for _, high, low, close, volume in rows:
        if volume > 0:
            typical = (high + low + close) / 3.0
            cum_pv += typical * volume
            cum_v += volume
        vwap_series.append((cum_pv / cum_v) if cum_v > 0 else None)
    session_vwap = vwap_series[-1]
    current_close = rows[-1][3]

    distance_to_vwap_pct = round(
        (current_close - session_vwap) / session_vwap * 100.0, 4)
    abs_dist = abs(distance_to_vwap_pct)
    if abs_dist <= VWAP_AT_THRESHOLD_PCT:
        price_position = "AT_VWAP"
        reasons.append("PRICE_AT_VWAP")
    elif distance_to_vwap_pct > 0:
        price_position = "ABOVE_VWAP"
        reasons.append("PRICE_ABOVE_VWAP")
    else:
        price_position = "BELOW_VWAP"
        reasons.append("PRICE_BELOW_VWAP")

    # ---- slope: last VWAP point vs K points ago, deadband 0.10% ----
    vwap_slope = "UNKNOWN"
    if len(vwap_series) >= VWAP_SLOPE_K + 1:
        vwap_now = vwap_series[-1]
        vwap_ago = vwap_series[-1 - VWAP_SLOPE_K]
        if vwap_now is not None and vwap_ago is not None and vwap_ago > 0:
            slope_pct = (vwap_now - vwap_ago) / vwap_ago * 100.0
            if abs(slope_pct) <= VWAP_SLOPE_FLAT_PCT:
                vwap_slope = "FLAT"
                reasons.append("VWAP_FLAT")
            elif slope_pct > 0:
                vwap_slope = "RISING"
                reasons.append("VWAP_RISING")
            else:
                vwap_slope = "FALLING"
                reasons.append("VWAP_FALLING")

    # ---- descriptive context (never drives the state decision) ----
    window = 5
    recent_closes = [row[3] for row in rows[-window:]]
    bars_above = sum(1 for c in recent_closes if c > session_vwap)
    bars_below = sum(1 for c in recent_closes if c < session_vwap)
    recent_context = {"window": window, "bars_above_vwap": bars_above,
                      "bars_below_vwap": bars_below}

    hourly_context = "INDETERMINATE"
    h_close = hourly.get("close")
    if h_close is not None:
        try:
            h_close_v = float(h_close)
            if math.isfinite(h_close_v) and h_close_v > 0 and session_vwap > 0:
                h_dist = (h_close_v - session_vwap) / session_vwap * 100.0
                if abs(h_dist) <= VWAP_AT_THRESHOLD_PCT:
                    hourly_context = "AT_VWAP"
                elif h_dist > 0:
                    hourly_context = "ABOVE_VWAP"
                else:
                    hourly_context = "BELOW_VWAP"
        except (TypeError, ValueError, OverflowError):
            hourly_context = "INDETERMINATE"

    # ---- coverage-aware confidence ----
    if bars_used >= 12:
        confidence = "HIGH"
    elif bars_used >= 6:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    if not health_ok and confidence == "HIGH":
        confidence = "MEDIUM"

    return result(session_date=session_date, session_status=session_status,
                  session_vwap=round(session_vwap, 4),
                  current_close=current_close,
                  distance_to_vwap_pct=distance_to_vwap_pct,
                  price_position=price_position, vwap_slope=vwap_slope,
                  bars_used=bars_used, total_volume=total_volume,
                  recent_context=recent_context,
                  hourly_context=hourly_context, data_health=health,
                  confidence=confidence, reason_codes=reasons)


@mcp.tool()
def get_session_vwap_snapshot(symbol: str, count: int = 80):
    """Read-only Session VWAP snapshot for US equities (15m session bars).

    Consumes Unified Data Health for session phase / trading-day authority
    (never re-derives stale/weekend/holiday logic), fetches 15m history,
    filters strictly to one regular session (bar-close semantics 09:45-16:00
    ET, 26 bars whole day), and delegates all math to the pure builder.
    Premarket/overnight uses the most recent complete session; after-hours
    uses today's completed session. 1H is context only (close vs same
    session VWAP), never a second VWAP. No positions, no AI, no runtime
    writes, no trading semantics.
    """
    generated_at = datetime.now().isoformat()
    health = data_health_check(symbol, timeframe="15m")
    if not isinstance(health, dict):
        health = {}
    session_phase = health.get("session_phase")
    session_date = health.get("expected_latest_trading_date")
    bars_response = get_bars(symbol, timeframe="15m", count=count)
    bars_15m = (bars_response.get("data")
                if isinstance(bars_response, dict) and bars_response.get("ok")
                else [])
    hourly = {}
    if session_date:
        hourly_response = get_bars(symbol, timeframe="1h", count=8)
        hourly_bars = (hourly_response.get("data")
                       if isinstance(hourly_response, dict)
                       and hourly_response.get("ok") else [])
        same_session = [
            row for row in hourly_bars
            if isinstance(row, dict)
            and isinstance(row.get("time_key"), str)
            and row["time_key"].startswith(session_date)
            and _vwap_is_regular_bar_close(row["time_key"])
        ]
        if same_session:
            hourly = {"close": same_session[-1].get("close")}
    return build_session_vwap_state({
        "generated_at": generated_at,
        "symbol": symbol,
        "session_date": session_date,
        "session_phase": session_phase,
        "bars_15m": bars_15m,
        "hourly": hourly,
        "data_health": health,
    })


# ============================================================================
# D4.2 -- Anchored VWAP Engine v0.1
#
# System swing anchors REUSE the D3 frozen 15m confirmed-swing authority
# (_structure_swings, n=2). This engine never re-scans pivots, never defines
# its own N, never consumes unconfirmed swings, never maps swings itself.
# anchor_confirmed_time = close of bar i+n (the bar that completes the
# right-side confirmation); before that time a swing is never observable
# (the shared _structure_swings only ever emits confirmed pivots), so no
# unconfirmed swing information can leak to the outside. Anchor accumulation
# starts at the anchor bar INCLUSIVE and crosses trading days, keeping only
# US regular-session 15m bars (Futu K_15M = BAR_CLOSE, (09:30, 16:00]).
#
# USER_SPECIFIED requires an exact 15m BAR_CLOSE timestamp; no nearest-bar
# snapping, no fallback, no guessing. Missing exact bar -> USER_ANCHOR_NOT_
# FOUND; outside history -> ANCHOR_OUTSIDE_AVAILABLE_HISTORY.
#
# Invalid OHLC / negative-non-numeric volume within an anchor span make that
# anchor's whole calculation INDETERMINATE (INVALID_PRICE_DATA /
# INVALID_VOLUME_DATA) - never silently dropped, never repaired.
# Conflicting duplicates -> INDETERMINATE (shared policy). zero-volume bars
# are kept (contribute nothing); all-zero span volume -> ZERO_VOLUME_SINCE_
# ANCHOR. No confluence semantics, no cross-anchor distance, no ratio
# thresholds: v0.1 confidence is purely coverage-based.
# ============================================================================

ANCHORED_VWAP_SCHEMA_VERSION = 1
AVWAP_AT_THRESHOLD_PCT = 0.20
AVWAP_MAX_TRADING_DAYS = 60
AVWAP_PRICE_POSITIONS = ("ABOVE_AVWAP", "AT_AVWAP", "BELOW_AVWAP",
                         "INDETERMINATE")
AVWAP_ANCHOR_TYPES = ("CONFIRMED_SWING_HIGH", "CONFIRMED_SWING_LOW",
                      "USER_SPECIFIED")
AVWAP_REASON_CODES = (
    "USER_ANCHOR_VALID", "USER_ANCHOR_NOT_FOUND", "USER_ANCHOR_INVALID",
    "SWING_HIGH_ANCHOR_VALID", "SWING_LOW_ANCHOR_VALID",
    "SWING_ANCHOR_UNAVAILABLE",
    "PRICE_ABOVE_AVWAP", "PRICE_AT_AVWAP", "PRICE_BELOW_AVWAP",
    "INSUFFICIENT_BARS_SINCE_ANCHOR", "ZERO_VOLUME_SINCE_ANCHOR",
    "ZERO_VOLUME_BARS_PRESENT",
    "INVALID_PRICE_DATA", "INVALID_VOLUME_DATA",
    "CONFLICTING_DUPLICATE_TIMESTAMP",
    "DATA_HEALTH_LIMITED", "ANCHOR_OUTSIDE_AVAILABLE_HISTORY",
    "ANCHOR_NOT_YET_CONFIRMED",
)


def _avwap_parse_bars(bars_15m):
    """Normalize regular-session 15m rows for the AVWAP engine.

    Returns (working_rows, flagged_map, conflicting):
      working_rows  - time-sorted, deduped dicts {time_key,high,low,close,
                      volume}; price-valid, volume>=0; volume 0 allowed.
      flagged_map   - {time_key: [reason_code,...]} for rows that carry
                      invalid OHLC (INVALID_PRICE_DATA) or negative /
                      non-numeric volume (INVALID_VOLUME_DATA). Never
                      silently dropped: their span poisons the anchor.
      conflicting   - True when identical time_key maps to different
                      OHLCV (shared duplicate policy).
    """
    regular = []
    for row in bars_15m or []:
        if not isinstance(row, dict):
            continue
        tk = row.get("time_key")
        if not isinstance(tk, str) or not _vwap_is_regular_bar_close(tk):
            continue
        regular.append((tk, row))
    dates = sorted({tk[:10] for tk, _ in regular})
    keep_dates = set(dates[-AVWAP_MAX_TRADING_DAYS:])
    in_window = [(tk, row) for tk, row in regular if tk[:10] in keep_dates]

    working = []
    flagged = {}
    for tk, row in in_window:
        try:
            high = float(row.get("high"))
            low = float(row.get("low"))
            close = float(row.get("close"))
        except (TypeError, ValueError, OverflowError):
            flagged.setdefault(tk, []).append("INVALID_PRICE_DATA")
            continue
        if not (all(math.isfinite(x) and x > 0 for x in (high, low, close))
                and high >= low and low <= close <= high):
            flagged.setdefault(tk, []).append("INVALID_PRICE_DATA")
            continue
        vol_raw = row.get("volume")
        if vol_raw is None:
            volume, vol_ok = 0.0, True
        else:
            vol_ok = True
            try:
                volume = float(vol_raw)
            except (TypeError, ValueError, OverflowError):
                volume, vol_ok = 0.0, False
            if not math.isfinite(volume):
                vol_ok = False
            if vol_ok and volume < 0:
                vol_ok = False
        if not vol_ok:
            flagged.setdefault(tk, []).append("INVALID_VOLUME_DATA")
            continue
        working.append({"time_key": tk, "high": high, "low": low,
                        "close": close, "volume": volume})
    working.sort(key=lambda r: r["time_key"])
    mapping, conflicting = _dedupe_bars_by_time(
        working, fields=("high", "low", "close", "volume"))
    deduped = []
    for key in sorted(mapping):
        hh, ll, cc, vv = mapping[key]
        deduped.append({"time_key": key, "high": hh, "low": ll,
                        "close": cc, "volume": vv})
    return deduped, flagged, conflicting


def _avwap_payload(rows_work, flagged_map, start_index, anchor_id,
                   anchor_type, anchor_source, anchor_bar_time,
                   anchor_confirmed_time, anchor_price, health_ok,
                   valid_code):
    """Deterministic per-anchor AVWAP payload (inclusive from anchor bar)."""
    subset = rows_work[start_index:]
    bars_used = len(subset)
    total_volume = sum(r["volume"] for r in subset)
    zero_volume_bars = sum(1 for r in subset if r["volume"] == 0)
    current_close = rows_work[-1]["close"]

    base = {
        "anchor_id": anchor_id, "anchor_type": anchor_type,
        "anchor_source": anchor_source, "anchor_bar_time": anchor_bar_time,
        "anchor_confirmed_time": anchor_confirmed_time,
        "anchor_price": anchor_price, "avwap": None,
        "current_close": current_close, "distance_pct": None,
        "price_position": "INDETERMINATE", "bars_used": bars_used,
        "total_volume": total_volume, "zero_volume_bars": zero_volume_bars,
        "confidence": "INDETERMINATE",
    }

    def finish(reasons):
        out = dict(base)
        out["reason_codes"] = sorted(set(reasons))
        return out

    reasons = []
    span_start = subset[0]["time_key"] if subset else anchor_bar_time
    span_end = subset[-1]["time_key"] if subset else anchor_bar_time
    # invalid OHLC / invalid volume inside the anchor span poison this anchor
    if flagged_map:
        for tk, codes in flagged_map.items():
            if span_start <= tk <= span_end:
                reasons.extend(codes)
    if any(c in ("INVALID_PRICE_DATA", "INVALID_VOLUME_DATA") for c in reasons):
        return finish(reasons)

    if anchor_confirmed_time and anchor_confirmed_time > span_end:
        reasons.append("ANCHOR_NOT_YET_CONFIRMED")
        return finish(reasons)
    if bars_used < 2:
        reasons.append("INSUFFICIENT_BARS_SINCE_ANCHOR")
        return finish(reasons)
    if total_volume <= 0:
        reasons.append("ZERO_VOLUME_SINCE_ANCHOR")
        return finish(reasons)

    cum_pv = 0.0
    cum_v = 0.0
    for r in subset:
        if r["volume"] > 0:
            typical = (r["high"] + r["low"] + r["close"]) / 3.0
            cum_pv += typical * r["volume"]
            cum_v += r["volume"]
    avwap = cum_pv / cum_v
    distance = round((current_close - avwap) / avwap * 100.0, 4)
    if abs(distance) <= AVWAP_AT_THRESHOLD_PCT:
        price_position = "AT_AVWAP"
        reasons.append("PRICE_AT_AVWAP")
    elif distance > 0:
        price_position = "ABOVE_AVWAP"
        reasons.append("PRICE_ABOVE_AVWAP")
    else:
        price_position = "BELOW_AVWAP"
        reasons.append("PRICE_BELOW_AVWAP")
    reasons.append(valid_code)
    if zero_volume_bars > 0:
        reasons.append("ZERO_VOLUME_BARS_PRESENT")
    if not health_ok:
        reasons.append("DATA_HEALTH_LIMITED")

    if bars_used >= 20:
        confidence = "HIGH"
    elif bars_used >= 8:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    if not health_ok and confidence == "HIGH":
        confidence = "MEDIUM"

    out = dict(base)
    out.update({"avwap": round(avwap, 4), "distance_pct": distance,
                "price_position": price_position, "confidence": confidence,
                "reason_codes": sorted(set(reasons))})
    return out


def _avwap_indet_slot(anchor_type, anchor_source, reason):
    return {
        "anchor_id": None, "anchor_type": anchor_type,
        "anchor_source": anchor_source, "anchor_bar_time": None,
        "anchor_confirmed_time": None, "anchor_price": None, "avwap": None,
        "current_close": None, "distance_pct": None,
        "price_position": "INDETERMINATE", "bars_used": 0,
        "total_volume": 0.0, "zero_volume_bars": 0,
        "confidence": "INDETERMINATE", "reason_codes": [reason],
    }


def build_anchored_vwap_state(vwap_input):
    """Pure deterministic Anchored VWAP builder.

    Input contract keys: generated_at, symbol, bars_15m, data_health,
    user_anchor_time (optional exact 'YYYY-MM-DD HH:MM:SS' 15m BAR_CLOSE).
    Three independent active slots: latest_swing_high / latest_swing_low
    (D3 15m confirmed-swing authority) and user_specified (never overwritten
    by system anchors; provenance per slot is independent). Pure function:
    no Moomoo call, no runtime write, no AI, no account access, no Regime /
    RS / Session-VWAP / Price-Structure / position consumption.
    """
    if not isinstance(vwap_input, dict):
        vwap_input = {}
    generated_at = vwap_input.get("generated_at")
    symbol = vwap_input.get("symbol")
    bars_15m = vwap_input.get("bars_15m") or []
    health = vwap_input.get("data_health") or {}
    health_ok = health.get("ok") is True and health.get("status") == "OK"
    user_anchor_time = vwap_input.get("user_anchor_time")

    rows_work, flagged_map, conflicting = _avwap_parse_bars(bars_15m)
    anchors = {"latest_swing_high": None, "latest_swing_low": None,
               "user_specified": None}

    def json_out():
        return clean_json_value({
            "schema_version": ANCHORED_VWAP_SCHEMA_VERSION,
            "generated_at": generated_at, "symbol": symbol,
            "anchors": anchors, "data_health": health,
        })

    def set_swing_high(payload):
        anchors["latest_swing_high"] = payload

    def set_swing_low(payload):
        anchors["latest_swing_low"] = payload

    def set_user(payload):
        anchors["user_specified"] = payload

    if conflicting:
        set_swing_high(_avwap_indet_slot(
            "CONFIRMED_SWING_HIGH", "D3_15M_CONFIRMED_SWING_HIGH",
            "CONFLICTING_DUPLICATE_TIMESTAMP"))
        set_swing_low(_avwap_indet_slot(
            "CONFIRMED_SWING_LOW", "D3_15M_CONFIRMED_SWING_LOW",
            "CONFLICTING_DUPLICATE_TIMESTAMP"))
        if user_anchor_time is not None:
            set_user(_avwap_indet_slot(
                "USER_SPECIFIED", "USER_SPECIFIED_15M_BAR_CLOSE",
                "CONFLICTING_DUPLICATE_TIMESTAMP"))
        return json_out()

    if not rows_work:
        set_swing_high(_avwap_indet_slot(
            "CONFIRMED_SWING_HIGH", "D3_15M_CONFIRMED_SWING_HIGH",
            "SWING_ANCHOR_UNAVAILABLE"))
        set_swing_low(_avwap_indet_slot(
            "CONFIRMED_SWING_LOW", "D3_15M_CONFIRMED_SWING_LOW",
            "SWING_ANCHOR_UNAVAILABLE"))
        if user_anchor_time is not None:
            set_user(_avwap_indet_slot(
                "USER_SPECIFIED", "USER_SPECIFIED_15M_BAR_CLOSE",
                "USER_ANCHOR_NOT_FOUND"))
        return json_out()

    # ---- D3 swing authority (direct reuse; indices align to rows_work) ----
    swing_rows = [{"high": r["high"], "low": r["low"]} for r in rows_work]
    n = 2
    swings = _structure_swings(swing_rows, n=n)
    swings_high = [s for s in swings if s["type"] == "HIGH"]
    swings_low = [s for s in swings if s["type"] == "LOW"]

    if swings_high:
        s = swings_high[-1]
        i = s["index"]
        set_swing_high(_avwap_payload(
            rows_work, flagged_map, i,
            anchor_id=f"{symbol}|CONFIRMED_SWING_HIGH|{rows_work[i]['time_key']}",
            anchor_type="CONFIRMED_SWING_HIGH",
            anchor_source="D3_15M_CONFIRMED_SWING_HIGH",
            anchor_bar_time=rows_work[i]["time_key"],
            anchor_confirmed_time=rows_work[i + n]["time_key"],
            anchor_price=s["price"], health_ok=health_ok,
            valid_code="SWING_HIGH_ANCHOR_VALID"))
    else:
        set_swing_high(_avwap_indet_slot(
            "CONFIRMED_SWING_HIGH", "D3_15M_CONFIRMED_SWING_HIGH",
            "SWING_ANCHOR_UNAVAILABLE"))

    if swings_low:
        s = swings_low[-1]
        i = s["index"]
        set_swing_low(_avwap_payload(
            rows_work, flagged_map, i,
            anchor_id=f"{symbol}|CONFIRMED_SWING_LOW|{rows_work[i]['time_key']}",
            anchor_type="CONFIRMED_SWING_LOW",
            anchor_source="D3_15M_CONFIRMED_SWING_LOW",
            anchor_bar_time=rows_work[i]["time_key"],
            anchor_confirmed_time=rows_work[i + n]["time_key"],
            anchor_price=s["price"], health_ok=health_ok,
            valid_code="SWING_LOW_ANCHOR_VALID"))
    else:
        set_swing_low(_avwap_indet_slot(
            "CONFIRMED_SWING_LOW", "D3_15M_CONFIRMED_SWING_LOW",
            "SWING_ANCHOR_UNAVAILABLE"))

    # ---- user_specified: exact bar-close timestamp, never snapped ----
    if user_anchor_time is not None:
        if not isinstance(user_anchor_time, str) or len(user_anchor_time) < 16:
            set_user(_avwap_indet_slot(
                "USER_SPECIFIED", "USER_SPECIFIED_15M_BAR_CLOSE",
                "USER_ANCHOR_INVALID"))
        else:
            keys = [r["time_key"] for r in rows_work]
            ut = str(user_anchor_time)
            if ut in keys:
                start_index = keys.index(ut)
                set_user(_avwap_payload(
                    rows_work, flagged_map, start_index,
                    anchor_id=f"{symbol}|USER_SPECIFIED|{ut}",
                    anchor_type="USER_SPECIFIED",
                    anchor_source="USER_SPECIFIED_15M_BAR_CLOSE",
                    anchor_bar_time=ut, anchor_confirmed_time=ut,
                    anchor_price=rows_work[start_index]["close"],
                    health_ok=health_ok, valid_code="USER_ANCHOR_VALID"))
            else:
                if ut in flagged_map:
                    # bar exists in the raw feed but carries invalid OHLC /
                    # volume: the exact anchor is present yet unusable ->
                    # INDETERMINATE with the concrete invalid code, never
                    # reported as "not found".
                    set_user({
                        "anchor_id": None, "anchor_type": "USER_SPECIFIED",
                        "anchor_source": "USER_SPECIFIED_15M_BAR_CLOSE",
                        "anchor_bar_time": None,
                        "anchor_confirmed_time": None, "anchor_price": None,
                        "avwap": None, "current_close": None,
                        "distance_pct": None,
                        "price_position": "INDETERMINATE", "bars_used": 0,
                        "total_volume": 0.0, "zero_volume_bars": 0,
                        "confidence": "INDETERMINATE",
                        "reason_codes": sorted(set(flagged_map[ut])),
                    })
                elif ut < keys[0] or ut > keys[-1]:
                    set_user(_avwap_indet_slot(
                        "USER_SPECIFIED", "USER_SPECIFIED_15M_BAR_CLOSE",
                        "ANCHOR_OUTSIDE_AVAILABLE_HISTORY"))
                else:
                    set_user(_avwap_indet_slot(
                        "USER_SPECIFIED", "USER_SPECIFIED_15M_BAR_CLOSE",
                        "USER_ANCHOR_NOT_FOUND"))
    return json_out()


def _fetch_15m_history_windowed(symbol, calendar_days=95):
    """Fetch up to ~60 trading days of 15m bars via the existing get_bars.

    Uses explicit start/end date paging (windows stay under the request cap),
    merges unique rows deterministically by time_key.
    """
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=calendar_days)
    merged = {}
    cursor = start_dt
    step = timedelta(days=23)
    while cursor < end_dt:
        win_end = min(cursor + step, end_dt)
        try:
            response = get_bars(symbol, timeframe="15m",
                                start=cursor.strftime("%Y-%m-%d"),
                                end=win_end.strftime("%Y-%m-%d"), count=1000)
        except Exception:
            response = {}
        data = (response.get("data")
                if isinstance(response, dict) and response.get("ok") else [])
        for row in data or []:
            tk = row.get("time_key")
            if isinstance(tk, str):
                merged[tk] = row
        cursor = win_end
    return [merged[k] for k in sorted(merged)]


@mcp.tool()
def get_anchored_vwap_snapshot(symbol: str, user_anchor_time: str | None = None):
    """Read-only Anchored VWAP snapshot (US equities).

    Fetches ~60 trading days of 15m regular-session bars, consumes Unified
    Data Health for freshness / session authority, and delegates all math to
    the pure build_anchored_vwap_state. latest_swing_high / latest_swing_low
    reuse the D3 frozen 15m confirmed-swing authority; user_anchor_time is an
    exact 15m BAR_CLOSE timestamp. No positions, no AI, no runtime writes,
    no trading semantics.
    """
    generated_at = datetime.now().isoformat()
    health = data_health_check(symbol, timeframe="15m")
    if not isinstance(health, dict):
        health = {}
    bars_15m = _fetch_15m_history_windowed(symbol)
    return build_anchored_vwap_state({
        "generated_at": generated_at,
        "symbol": symbol,
        "bars_15m": bars_15m,
        "data_health": health,
        "user_anchor_time": user_anchor_time,
    })






@mcp.tool()
def run_claude_real_analysis(ai_request: dict):
    """Explicitly run one Common AI Request through Claude real transport."""
    return ClaudeRealAdapter().analyze(ai_request)


@mcp.tool()
def run_deepseek_real_analysis(ai_request: dict):
    """Explicitly run one Common AI Request through DeepSeek real transport."""
    return DeepSeekRealAdapter().analyze(ai_request)


@mcp.tool()
def run_real_multi_model_analysis(ai_request: dict, mode: str = "PRIMARY"):
    """Explicitly route one Common AI Request through real model adapters."""
    return route_ai_requests([ai_request], mode=mode, execution_profile="REAL")


@mcp.tool()
def run_primary_trigger_cycle(count: int = 20):
    """Compare primary market state and atomically advance the local baseline."""
    current_analysis = get_primary_analysis_state(count=count)
    current_snapshot = build_trigger_snapshot(current_analysis)
    if current_snapshot.get("ok") is False:
        return {
            "ok": False,
            "status": "ANALYSIS_UNAVAILABLE",
            "error": current_analysis.get("error") if isinstance(current_analysis, dict) else None,
        }

    loaded = load_runtime_state()
    if not loaded.get("ok"):
        return loaded
    previous_runtime = loaded.get("state")
    if previous_runtime is not None:
        previous_snapshot = previous_runtime["previous_snapshot"]
        if previous_snapshot["account_alias"] != current_snapshot["account_alias"]:
            return {"ok": False, "status": "ACCOUNT_MISMATCH"}
        trigger_result = compare_analysis_states(
            _trigger_snapshot_for_compare(previous_snapshot),
            _trigger_snapshot_for_compare(current_snapshot),
        )
        if not trigger_result.get("ok"):
            return trigger_result
    else:
        trigger_result = compare_analysis_states(
            None,
            _trigger_snapshot_for_compare(current_snapshot),
        )

    suppression = apply_event_suppression(
        trigger_result["events"],
        previous_runtime.get("event_runtime", {}) if previous_runtime else {},
        now=current_snapshot["snapshot_time"],
    )
    if not suppression.get("ok"):
        return suppression

    ai_gate = build_ai_invocation_plan(
        suppression["actionable_events"],
        current_analysis,
    )
    if not ai_gate.get("ok"):
        return ai_gate

    ai_requests = []
    for invocation_request in ai_gate["requests"]:
        request = build_ai_analysis_request(invocation_request, current_analysis)
        if request.get("ok") is False:
            return request
        ai_requests.append(request)

    runtime_state = {
        "schema_version": RUNTIME_STATE_SCHEMA_VERSION,
        "updated_at": current_snapshot["snapshot_time"],
        "account_alias": current_snapshot["account_alias"],
        "previous_snapshot": current_snapshot,
        "last_trigger_events": trigger_result["events"],
        "event_runtime": suppression["event_runtime"],
    }
    saved = save_runtime_state(runtime_state)
    if not saved.get("ok"):
        return saved

    return {
        "ok": True,
        "baseline_created": previous_runtime is None,
        "raw_triggered": trigger_result["triggered"],
        "triggered": suppression["actionable_event_count"] > 0,
        "raw_event_count": suppression["raw_event_count"],
        "actionable_event_count": suppression["actionable_event_count"],
        "suppressed_event_count": suppression["suppressed_event_count"],
        "highest_actionable_severity": suppression["highest_actionable_severity"],
        "raw_events": suppression["raw_events"],
        "actionable_events": suppression["actionable_events"],
        "suppressed_events": suppression["suppressed_events"],
        "should_invoke_ai": ai_gate["should_invoke_ai"],
        "ai_request_count": ai_gate["request_count"],
        "ai_gate": ai_gate,
        "ai_requests": ai_requests,
    }


@mcp.tool()
def get_account_list():
    """Read available Moomoo JP US trading accounts. Read-only."""
    ctx = get_us_trade_ctx()

    try:
        ret, data = ctx.get_acc_list()

        if ret != RET_OK:
            return {
                "ok": False,
                "error": str(data)
            }

        records = data.to_dict(orient="records")

        for row in records:
            if "acc_id" in row:
                row["acc_id"] = str(row["acc_id"])

        return {
            "ok": True,
            "accounts": records
        }

    finally:
        ctx.close()


@mcp.tool()
def get_positions(acc_id: str):
    """Read positions for a specific Moomoo account. Read-only."""
    ctx = get_us_trade_ctx()

    try:
        account_id = int(acc_id)

        ret, data = ctx.position_list_query(
            acc_id=account_id,
            trd_env=TrdEnv.REAL,
        )

        if ret != RET_OK:
            return {
                "ok": False,
                "error": str(data)
            }

        return {
            "ok": True,
            "positions": data.to_dict(orient="records")
        }

    finally:
        ctx.close()

@mcp.tool()
def get_portfolio_state(acc_id: str):
    """Return normalized live portfolio state for a Moomoo account. Read-only."""
    ctx = get_us_trade_ctx()

    try:
        account_id = int(acc_id)

        ret, data = ctx.position_list_query(
            acc_id=account_id,
            trd_env=TrdEnv.REAL,
        )

        if ret != RET_OK:
            return {
                "ok": False,
                "error": str(data)
            }

        positions = []

        for _, row in data.iterrows():
            qty = row.get("qty", 0)

            try:
                qty_value = float(qty)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(qty_value) or qty_value == 0:
                continue

            positions.append({
                "symbol": row.get("code"),
                "name": row.get("stock_name"),
                "quantity": row.get("qty"),
                "cost_price": row.get("cost_price"),
                "market_price": row.get("nominal_price"),
                "market_value": row.get("market_val"),
                "pnl": row.get("pl_val"),
                "pnl_ratio": row.get("pl_ratio"),
                "currency": row.get("currency"),
            })

        return {
            "ok": True,
            "snapshot_time": datetime.now().isoformat(),
            "account_id": acc_id,
            "position_count": len(positions),
            "positions": positions,
        }

    finally:
        ctx.close()

@mcp.tool()
def get_primary_portfolio_state():
    """Return normalized live portfolio state for the primary US account. Read-only."""
    return get_portfolio_state(require_primary_us_account_id())


@mcp.tool()
def get_primary_symbols():
    """Return all held symbols from the primary US account. Read-only."""
    state = get_portfolio_state(require_primary_us_account_id())

    if not state.get("ok"):
        return state

    symbols = [
        position.get("symbol")
        for position in state.get("positions", [])
        if position.get("symbol")
    ]

    return {
        "ok": True,
        "count": len(symbols),
        "symbols": symbols,
    }


@mcp.tool()
def get_primary_position_bars(count: int = 60):
    """Return Daily, 1H and 15m bars for all positions in the primary US account."""
    state = get_portfolio_state(require_primary_us_account_id())

    if not state.get("ok"):
        return state

    result = {}

    for position in state.get("positions", []):
        symbol = position.get("symbol")

        if not symbol:
            continue

        result[symbol] = {
            "daily": get_bars(
                symbol=symbol,
                timeframe="1d",
                count=count,
            ),
            "hourly": get_bars(
                symbol=symbol,
                timeframe="1h",
                count=count,
            ),
            "15m": get_bars(
                symbol=symbol,
                timeframe="15m",
                count=count,
            ),
        }

    return {
        "ok": True,
        "symbol_count": len(result),
        "bars_per_timeframe": count,
        "data": result,
    }


@mcp.tool()
def get_primary_market_bundle(count: int = 60):
    """Return normalized market bundle for all primary US positions. Read-only."""
    state = get_portfolio_state(require_primary_us_account_id())

    if not state.get("ok"):
        return state

    result = {}

    for position in state.get("positions", []):
        symbol = position.get("symbol")

        if not symbol:
            continue

        result[symbol] = {
            "position": position,
            "quote_summary": get_quote_summary(symbol),
            "bars": {
                "daily": get_bars(
                    symbol=symbol,
                    timeframe="1d",
                    count=count,
                ),
                "hourly": get_bars(
                    symbol=symbol,
                    timeframe="1h",
                    count=count,
                ),
                "15m": get_bars(
                    symbol=symbol,
                    timeframe="15m",
                    count=count,
                ),
            },
        }

    result_bundle = {
        "ok": True,
        "snapshot_time": datetime.now().isoformat(),
        "account_alias": "MOOMOO_US_PRIMARY",
        "symbol_count": len(result),
        "bars_per_timeframe": count,
        "positions": result,
    }

    return clean_json_value(result_bundle)


_BUNDLE_STATUS_TIER_RANK = {
    "DATA_UNAVAILABLE": 3,
    "STALE_OR_MISALIGNED": 2,
    "CURRENTNESS_UNVERIFIED": 1,
    "OK": 0,
}


def _bundle_status_tier(raw_status):
    """Classify one already-emitted child status into a bundle-level tier.

    Buckets a value _data_health_check_core (or a bundle completeness check)
    already produced; computes no freshness judgment of its own. Only OK,
    STALE_OR_MISALIGNED and CURRENTNESS_UNVERIFIED are passed through as-is
    -- every other value (DATA_UNAVAILABLE itself, and every core
    error-shaped status such as SNAPSHOT_ERROR / SNAPSHOT_EMPTY / BAR_ERROR /
    BAR_EMPTY / UNSUPPORTED_TIMEFRAME / CALENDAR_UNAVAILABLE) is treated as
    DATA_UNAVAILABLE-tier, fail closed.
    """
    if raw_status in ("OK", "STALE_OR_MISALIGNED", "CURRENTNESS_UNVERIFIED"):
        return raw_status
    return "DATA_UNAVAILABLE"


def _reduce_bundle_status(tiers):
    """Pure precedence reduction over already-classified bundle tiers.

    DATA_UNAVAILABLE > STALE_OR_MISALIGNED > CURRENTNESS_UNVERIFIED > OK.
    Selects among values already produced elsewhere; performs no new
    Currentness calculation and no positive freshness inference.
    """
    if not tiers:
        return "DATA_UNAVAILABLE"
    return max(tiers, key=_BUNDLE_STATUS_TIER_RANK.get)


@mcp.tool()
def get_primary_market_bundle_health(count: int = 60):
    """Run unified Data Health checks on the primary US market bundle. Read-only.

    Freshness / stale / session / calendar judgments come exclusively from
    _data_health_check_core (the single system-wide authority). This function
    only adds bundle-level completeness: whether quote and per-timeframe bars
    exist, plus a deterministic multi-timeframe aggregation of authority
    output. No quote/bar date equality is performed here.
    """
    bundle = get_primary_market_bundle(count=count)

    if not bundle.get("ok"):
        return {
            "ok": False,
            "overall_status": "DATA_UNAVAILABLE",
            "error": bundle.get("error"),
        }

    health = {}
    statuses = []
    q = get_quote_ctx()

    try:
        end_dt = datetime.now()
        calendar_start = end_dt - timedelta(days=20)
        calendar_end = end_dt + timedelta(days=1)
        trading_day_map = _fetch_us_trading_days(
            q,
            start_date=calendar_start.strftime("%Y-%m-%d"),
            end_date=calendar_end.strftime("%Y-%m-%d"),
        )
        now_et = _us_eastern_now()

        for symbol, item in bundle.get("positions", {}).items():
            quote = item.get("quote_summary", {})
            bars = item.get("bars", {})

            daily = bars.get("daily", {})
            hourly = bars.get("hourly", {})
            bars_15m = bars.get("15m", {})

            quote_ok = quote.get("ok") is True
            daily_ok = daily.get("ok") is True
            hourly_ok = hourly.get("ok") is True
            bars_15m_ok = bars_15m.get("ok") is True

            latest_quote = quote.get("snapshot_time")

            latest_daily = None
            latest_hourly = None
            latest_15m = None

            if daily_ok and daily.get("data"):
                latest_daily = daily["data"][-1].get("time_key")

            if hourly_ok and hourly.get("data"):
                latest_hourly = hourly["data"][-1].get("time_key")

            if bars_15m_ok and bars_15m.get("data"):
                latest_15m = bars_15m["data"][-1].get("time_key")

            timeframe_authority = {}
            for timeframe_name, bars_ok, api_tf in (
                ("daily", daily_ok, "1d"),
                ("hourly", hourly_ok, "1h"),
                ("15m", bars_15m_ok, "15m"),
            ):
                if not bars_ok:
                    timeframe_authority[timeframe_name] = {
                        "status": "DATA_UNAVAILABLE",
                        "symbol": symbol,
                        "timeframe": api_tf,
                        "reason_codes": ["BARS_UNAVAILABLE"],
                    }
                else:
                    timeframe_authority[timeframe_name] = _data_health_check_core(
                        q,
                        symbol,
                        timeframe=api_tf,
                        now_et=now_et,
                        trading_day_map=trading_day_map,
                        calendar_unavailable=trading_day_map is None,
                    )

            timeframe_statuses = {
                name: entry.get("status")
                for name, entry in timeframe_authority.items()
            }
            components_present = (
                quote_ok and daily_ok and hourly_ok and bars_15m_ok
            )
            if not components_present:
                status = "DATA_UNAVAILABLE"
            else:
                status = _reduce_bundle_status(
                    _bundle_status_tier(value)
                    for value in timeframe_statuses.values()
                )

            reason_codes = []
            if not quote_ok:
                reason_codes.append("QUOTE_UNAVAILABLE")
            for timeframe_name, entry in timeframe_authority.items():
                entry_status = entry.get("status")
                if entry_status != "OK":
                    entry_reason_codes = entry.get("reason_codes") or []
                    if entry_reason_codes:
                        reason_codes.extend(entry_reason_codes)
                    else:
                        # Core error-shaped statuses (SNAPSHOT_ERROR,
                        # SNAPSHOT_EMPTY, BAR_ERROR, BAR_EMPTY,
                        # UNSUPPORTED_TIMEFRAME) carry no native reason_codes;
                        # fall back to the raw status itself so the
                        # aggregation cause is never silently lost.
                        reason_codes.append(entry_status)
            reason_codes = sorted(set(reason_codes))

            statuses.append(status)
            health[symbol] = {
                "status": status,
                "quote_ok": quote_ok,
                "daily_ok": daily_ok,
                "hourly_ok": hourly_ok,
                "15m_ok": bars_15m_ok,
                "latest_times": {
                    "quote": latest_quote,
                    "daily": latest_daily,
                    "hourly": latest_hourly,
                    "15m": latest_15m,
                },
                "timeframes": timeframe_authority,
                "reason_codes": reason_codes,
                "authority": "data_health_check",
            }
    finally:
        q.close()

    overall_status = _reduce_bundle_status(statuses)

    return {
        "ok": True,
        "overall_status": overall_status,
        "symbol_count": len(health),
        "health": health,
    }


@mcp.tool()
def get_primary_analysis_state(count: int = 60):
    """Return normalized analysis input for all primary US positions. Read-only."""

    indicator_count = max(count, 100) if count > 0 else count
    bundle = get_primary_market_bundle(count=indicator_count)
    health_result = get_primary_market_bundle_health(count=count)

    if not bundle.get("ok"):
        return {
            "ok": False,
            "error": bundle.get("error"),
        }

    if not health_result.get("ok"):
        return {
            "ok": False,
            "error": health_result.get("error"),
        }

    result = {}

    health_map = health_result.get("health", {})

    for symbol, item in bundle.get("positions", {}).items():
        position = item.get("position", {})
        quote = item.get("quote_summary", {})
        bars = item.get("bars", {})
        health = health_map.get(symbol, {})
        daily_bars = bars.get("daily", {}).get("data", [])
        hourly_bars = bars.get("hourly", {}).get("data", [])
        bars_15m = bars.get("15m", {}).get("data", [])
        indicators = {
            "daily": calculate_indicators_from_bars(daily_bars),
            "hourly": calculate_indicators_from_bars(hourly_bars),
            "15m": calculate_indicators_from_bars(bars_15m),
        }
        timeframe_state = {
            key: summarize_timeframe_state(value)
            for key, value in indicators.items()
        }
        timeframe_state["overall"] = summarize_timeframe_alignment(timeframe_state)

        result[symbol] = {
            "position": {
                "quantity": position.get("quantity"),
                "cost_price": position.get("cost_price"),
                "market_price": position.get("market_price"),
                "market_value": position.get("market_value"),
                "pnl": position.get("pnl"),
                "pnl_ratio": position.get("pnl_ratio"),
                "currency": position.get("currency"),
            },
            "market": {
                "last_price": (
                    quote.get("price", {}).get("last")
                    if quote.get("ok")
                    else None
                ),
                "change_rate_pct": (
                    quote.get("price", {}).get("change_rate_pct")
                    if quote.get("ok")
                    else None
                ),
                "volume": (
                    quote.get("market_activity", {}).get("volume")
                    if quote.get("ok")
                    else None
                ),
                "volume_ratio": (
                    quote.get("market_activity", {}).get("volume_ratio")
                    if quote.get("ok")
                    else None
                ),
                "status": quote.get("status"),
            },
            "bars": {
                "daily": daily_bars[-count:],
                "hourly": hourly_bars[-count:],
                "15m": bars_15m[-count:],
            },
            "indicators": indicators,
            "timeframe_state": timeframe_state,
            "data_health": {
                "status": health.get("status"),
                "latest_times": health.get("latest_times"),
                "timeframes": health.get("timeframes"),
                "reason_codes": health.get("reason_codes"),
                "authority": "data_health_check",
            },
        }

    return clean_json_value({
        "ok": True,
        "snapshot_time": bundle.get("snapshot_time"),
        "account_alias": bundle.get("account_alias"),
        "overall_data_health": health_result.get("overall_status"),
        "symbol_count": len(result),
        "analysis_state": result,
    })


@mcp.tool()
def get_snapshot(symbol: str):
    """Get a compact market snapshot for AI analysis."""
    q = get_quote_ctx()

    try:
        ret, data = q.get_market_snapshot([symbol])

        if ret != RET_OK:
            return {
                "ok": False,
                "error": str(data)
            }

        records = data.to_dict(orient="records")

        if not records:
            return {
                "ok": False,
                "error": "no snapshot data returned"
            }

        row = records[0]

        fields = [
            "code",
            "name",
            "update_time",
            "last_price",
            "open_price",
            "high_price",
            "low_price",
            "prev_close_price",
            "volume",
            "turnover",
            "turnover_rate",
            "avg_price",
            "amplitude",
            "bid_price",
            "ask_price",
            "bid_vol",
            "ask_vol",
            "bid_ask_ratio",
            "volume_ratio",
            "highest52weeks_price",
            "lowest52weeks_price",
            "total_market_val",
            "circular_market_val",
            "earning_per_share",
            "pe_ratio",
            "pe_ttm_ratio",
            "pb_ratio",
            "dividend_ttm",
            "dividend_ratio_ttm",
            "pre_price",
            "pre_change_rate",
            "after_price",
            "after_change_rate",
            "overnight_price",
            "overnight_change_rate",
            "sec_status",
        ]

        compact = {
            key: row.get(key)
            for key in fields
        }

        return {
            "ok": True,
            "data": compact
        }

    finally:
        q.close()


@mcp.tool()
def get_quote_summary(symbol: str):
    """Get a concise market summary for AI analysis."""
    q = get_quote_ctx()

    try:
        ret, data = q.get_market_snapshot([symbol])

        if ret != RET_OK:
            return {
                "ok": False,
                "error": str(data)
            }

        records = data.to_dict(orient="records")

        if not records:
            return {
                "ok": False,
                "error": "no snapshot data returned"
            }

        row = records[0]

        last_price = row.get("last_price")
        prev_close = row.get("prev_close_price")

        change = None
        change_rate = None

        if (
            isinstance(last_price, (int, float))
            and isinstance(prev_close, (int, float))
            and prev_close not in (0, None)
        ):
            change = last_price - prev_close
            change_rate = (change / prev_close) * 100

        return {
            "ok": True,
            "symbol": row.get("code"),
            "name": row.get("name"),
            "snapshot_time": row.get("update_time"),

            "price": {
                "last": last_price,
                "change": change,
                "change_rate_pct": change_rate,
                "open": row.get("open_price"),
                "high": row.get("high_price"),
                "low": row.get("low_price"),
                "prev_close": prev_close,
                "avg_price": row.get("avg_price"),
            },

            "market_activity": {
                "volume": row.get("volume"),
                "turnover": row.get("turnover"),
                "turnover_rate": row.get("turnover_rate"),
                "volume_ratio": row.get("volume_ratio"),
                "amplitude_pct": row.get("amplitude"),
            },

            "orderbook_top": {
                "bid": row.get("bid_price"),
                "bid_vol": row.get("bid_vol"),
                "ask": row.get("ask_price"),
                "ask_vol": row.get("ask_vol"),
                "bid_ask_ratio": row.get("bid_ask_ratio"),
            },

            "valuation": {
                "market_cap": row.get("total_market_val"),
                "pe": row.get("pe_ratio"),
                "pe_ttm": row.get("pe_ttm_ratio"),
                "pb": row.get("pb_ratio"),
                "eps": row.get("earning_per_share"),
                "dividend_ttm": row.get("dividend_ttm"),
                "dividend_yield_ttm": row.get("dividend_ratio_ttm"),
            },

            "range_52w": {
                "high": row.get("highest52weeks_price"),
                "low": row.get("lowest52weeks_price"),
            },

            "extended_hours": {
                "pre_price": row.get("pre_price"),
                "pre_change_rate": row.get("pre_change_rate"),
                "after_price": row.get("after_price"),
                "after_change_rate": row.get("after_change_rate"),
                "overnight_price": row.get("overnight_price"),
                "overnight_change_rate": row.get("overnight_change_rate"),
            },

            "status": row.get("sec_status"),
        }

    finally:
        q.close()


@mcp.tool()
def get_snapshot_full(symbol: str):
    """Get the full raw Moomoo market snapshot."""
    q = get_quote_ctx()

    try:
        ret, data = q.get_market_snapshot([symbol])

        if ret != RET_OK:
            return {
                "ok": False,
                "error": str(data)
            }

        return {
            "ok": True,
            "data": data.to_dict(orient="records")
        }

    finally:
        q.close()


@mcp.tool()
def get_bars(
    symbol: str,
    timeframe: str = "15m",
    start: str | None = None,
    end: str | None = None,
    count: int = 100,
):
    """
    Get historical bars.

    If start/end are omitted, return the latest N bars.
    Supported timeframes:
    1m, 5m, 15m, 30m, 60m, 1h, day, 1d
    """

    mapping = {
        "1m": KLType.K_1M,
        "5m": KLType.K_5M,
        "15m": KLType.K_15M,
        "30m": KLType.K_30M,
        "60m": KLType.K_60M,
        "1h": KLType.K_60M,
        "day": KLType.K_DAY,
        "1d": KLType.K_DAY,
    }

    if timeframe not in mapping:
        return {
            "ok": False,
            "error": f"unsupported timeframe: {timeframe}"
        }

    if count <= 0:
        return {
            "ok": False,
            "error": "count must be greater than 0"
        }

    # No explicit date range:
    # search a recent window and then return the latest N bars.
    if start is None and end is None:
        end_dt = datetime.now()

        lookback_days = {
            "1m": 5,
            "5m": 10,
            "15m": 20,
            "30m": 30,
            "60m": 60,
            "1h": 60,
            "day": 365,
            "1d": 365,
        }[timeframe]

        start_dt = end_dt - timedelta(days=lookback_days)

        start = start_dt.strftime("%Y-%m-%d")
        end = end_dt.strftime("%Y-%m-%d")

    q = get_quote_ctx()

    try:
        ret, data, _ = q.request_history_kline(
            symbol,
            start=start,
            end=end,
            ktype=mapping[timeframe],
            max_count=1000,
        )

        if ret != RET_OK:
            return {
                "ok": False,
                "error": str(data)
            }

        data = data.tail(count)

        return {
            "ok": True,
            "count": len(data),
            "data": data.to_dict(orient="records")
        }

    finally:
        q.close()


@mcp.tool()
def get_orderbook(symbol: str, depth: int = 10):
    """Get current order book. Read-only."""
    q = get_quote_ctx()

    try:
        ret, msg = q.subscribe(
            [symbol],
            [SubType.ORDER_BOOK]
        )

        if ret != RET_OK:
            return {
                "ok": False,
                "error": str(msg)
            }

        ret, data = q.get_order_book(
            symbol,
            num=depth
        )

        if ret != RET_OK:
            return {
                "ok": False,
                "error": str(data)
            }

        return {
            "ok": True,
            "data": data
        }

    finally:
        q.close()


def _us_eastern_utc_offset_hours(naive_utc):
    """UTC->ET offset for a naive UTC datetime (fixed US post-2007 DST rule).

    DST begins at 02:00 local on the second Sunday of March and ends at
    02:00 local on the first Sunday of November. Offsets: EST=-5, EDT=-4.
    This is a transparent, offline-testable helper; no external calendar I/O.
    """

    def nth_sunday(month, count):
        day = 1
        seen = 0
        while True:
            if date(naive_utc.year, month, day).weekday() == 6:
                seen += 1
                if seen == count:
                    return datetime(naive_utc.year, month, day, 2, 0)
            day += 1

    # 02:00 local time expressed in UTC for each offset regime:
    # DST begins at 07:00 UTC (02:00 EST), ends at 06:00 UTC (02:00 EDT).
    dst_start_utc = nth_sunday(3, 2) + timedelta(hours=5)
    dst_end_utc = nth_sunday(11, 1) + timedelta(hours=4)
    return -4 if dst_start_utc <= naive_utc < dst_end_utc else -5


def _us_eastern_now():
    """Naive US Eastern Time derived from UTC without external I/O."""
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    return now_utc + timedelta(hours=_us_eastern_utc_offset_hours(now_utc))


def _us_session_phase(now_et):
    """Clock-only session phase; trading-day awareness comes from the calendar.

    Limitation: half-day (early close) sessions are not modelled here; the
    trading-day calendar resolves them at date granularity instead.
    """
    current = now_et.time()
    if time(9, 30) <= current < time(16, 0):
        return "REGULAR"
    if time(4, 0) <= current < time(9, 30):
        return "PREMARKET"
    if time(16, 0) <= current < time(20, 0):
        return "AFTER_HOURS"
    return "OVERNIGHT_CLOSED"


def _expected_latest_trading_date(now_et, trading_days):
    """Latest trading date whose regular-session bar should exist by now.

    trading_days is an iterable of YYYY-MM-DD strings from the single
    trading-calendar source. Pure function, no I/O.
    """
    if not trading_days:
        return None
    today = now_et.date().isoformat()
    if today in trading_days and _us_session_phase(now_et) in ("REGULAR", "AFTER_HOURS"):
        return today
    candidates = sorted(value for value in trading_days if value < today)
    return candidates[-1] if candidates else None


_US_RTH_COMPLETED_BAR_ENDS = {
    "15m": (time(9, 45), time(10, 0), time(10, 15), time(10, 30),
            time(10, 45), time(11, 0), time(11, 15), time(11, 30),
            time(11, 45), time(12, 0), time(12, 15), time(12, 30),
            time(12, 45), time(13, 0), time(13, 15), time(13, 30),
            time(13, 45), time(14, 0), time(14, 15), time(14, 30),
            time(14, 45), time(15, 0), time(15, 15), time(15, 30),
            time(15, 45), time(16, 0)),
    "60m": (time(10, 30), time(11, 30), time(12, 30), time(13, 30),
            time(14, 30), time(15, 30), time(16, 0)),
    "1h": (time(10, 30), time(11, 30), time(12, 30), time(13, 30),
           time(14, 30), time(15, 30), time(16, 0)),
}


def expected_completed_bar_end(now_et, timeframe):
    """Return the latest completed normal-US-RTH bar-end time, or None."""
    phase = _us_session_phase(now_et)
    if phase not in ("REGULAR", "AFTER_HOURS"):
        return None
    grid = _US_RTH_COMPLETED_BAR_ENDS.get(timeframe)
    if not grid:
        return None
    completed = [value for value in grid if value <= now_et.time()]
    return completed[-1] if completed else None


def _fetch_us_trading_days(q, start_date, end_date):
    """US trading-day calendar from OpenD; no hardcoded holiday lists.

    Returns a dict mapping YYYY-MM-DD -> trade_date_type (WHOLE/HALF) or
    None when the calendar is unavailable.
    """
    try:
        ret, data = q.request_trading_days(Market.US, start=start_date, end=end_date)
    except Exception:
        return None
    if ret != RET_OK or not isinstance(data, list) or not data:
        return None
    result = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        day = str(item.get("time", ""))[:10]
        if len(day) == 10:
            result[day] = str(item.get("trade_date_type", "WHOLE"))
    return result or None


def _data_health_check_core(q, symbol, timeframe, now_et=None,
                            trading_day_map=None, calendar_unavailable=False):
    """Shared Data Health authority core (the single system-wide freshness rule).

    All freshness / stale / session-phase / trading-calendar logic lives here.
    data_health_check(), get_market_regime_snapshot() and
    get_primary_market_bundle_health() all consume this core; downstream
    modules must not re-derive freshness on their own. The caller owns the
    quote-context lifecycle. now_et and trading_day_map are injectable for
    deterministic offline tests and for sharing one calendar fetch across
    many timeframe checks.
    """
    ret, snap = q.get_market_snapshot([symbol])

    if ret != RET_OK:
        return {
            "ok": False,
            "status": "SNAPSHOT_ERROR",
            "error": str(snap),
        }

    records = snap.to_dict(orient="records")

    if not records:
        return {
            "ok": False,
            "status": "SNAPSHOT_EMPTY",
        }

    snapshot_time = records[0].get("update_time")

    mapping = {
        "1m": KLType.K_1M,
        "5m": KLType.K_5M,
        "15m": KLType.K_15M,
        "30m": KLType.K_30M,
        "60m": KLType.K_60M,
        "1h": KLType.K_60M,
        "day": KLType.K_DAY,
        "1d": KLType.K_DAY,
    }

    if timeframe not in mapping:
        return {
            "ok": False,
            "status": "UNSUPPORTED_TIMEFRAME",
            "error": timeframe,
        }

    end_dt = datetime.now()

    lookback_days = {
        "1m": 5,
        "5m": 10,
        "15m": 20,
        "30m": 30,
        "60m": 60,
        "1h": 60,
        "day": 365,
        "1d": 365,
    }[timeframe]

    start_dt = end_dt - timedelta(days=lookback_days)

    ret, bars, _ = q.request_history_kline(
        symbol,
        start=start_dt.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
        ktype=mapping[timeframe],
        max_count=1000,
    )

    if ret != RET_OK:
        return {
            "ok": False,
            "status": "BAR_ERROR",
            "error": str(bars),
        }

    if bars.empty:
        return {
            "ok": False,
            "status": "BAR_EMPTY",
        }

    latest_bar_time = bars.iloc[-1]["time_key"]

    if trading_day_map is None:
        if calendar_unavailable:
            return {
                "ok": False,
                "status": "CALENDAR_UNAVAILABLE",
                "symbol": symbol,
                "timeframe": timeframe,
                "snapshot_time": snapshot_time,
                "latest_bar_time": latest_bar_time,
                "reason_codes": ["TRADING_CALENDAR_UNAVAILABLE"],
            }
        calendar_start = end_dt - timedelta(days=20)
        calendar_end = end_dt + timedelta(days=1)
        trading_day_map = _fetch_us_trading_days(
            q,
            start_date=calendar_start.strftime("%Y-%m-%d"),
            end_date=calendar_end.strftime("%Y-%m-%d"),
        )

        if trading_day_map is None:
            return {
                "ok": False,
                "status": "CALENDAR_UNAVAILABLE",
                "symbol": symbol,
                "timeframe": timeframe,
                "snapshot_time": snapshot_time,
                "latest_bar_time": latest_bar_time,
                "reason_codes": ["TRADING_CALENDAR_UNAVAILABLE"],
            }

    if now_et is None:
        now_et = _us_eastern_now()

    expected_date = _expected_latest_trading_date(now_et, set(trading_day_map))

    if expected_date is None:
        return {
            "ok": False,
            "status": "CALENDAR_UNAVAILABLE",
            "symbol": symbol,
            "timeframe": timeframe,
            "snapshot_time": snapshot_time,
            "latest_bar_time": latest_bar_time,
            "reason_codes": ["NO_TRADING_DAYS_IN_CALENDAR_WINDOW"],
        }

    bar_date = str(latest_bar_time)[:10]

    if bar_date == expected_date:
        if timeframe in ("day", "1d"):
            status = "OK"
            reasons = ["LATEST_BAR_MATCHES_EXPECTED_SESSION"]
        elif timeframe in ("15m", "60m", "1h"):
            if trading_day_map.get(expected_date) != "WHOLE":
                status = "CURRENTNESS_UNVERIFIED"
                reasons = ["UNSUPPORTED_SESSION_SCOPE"]
            else:
                try:
                    parsed = datetime.strptime(str(latest_bar_time), "%Y-%m-%d %H:%M:%S")
                    expected_end = expected_completed_bar_end(now_et, timeframe)
                except (TypeError, ValueError):
                    parsed = None
                    expected_end = None
                grid = _US_RTH_COMPLETED_BAR_ENDS.get(timeframe, ())
                if parsed is None:
                    status = "CURRENTNESS_UNVERIFIED"
                    reasons = ["TIMESTAMP_FORMAT_OR_PROVENANCE_UNSUPPORTED"]
                elif expected_end is None:
                    status = "CURRENTNESS_UNVERIFIED"
                    reasons = ["UNSUPPORTED_SESSION_SCOPE"]
                elif parsed.time() not in grid:
                    status = "CURRENTNESS_UNVERIFIED"
                    reasons = ["TIMESTAMP_OFF_ADMITTED_GRID"]
                elif parsed.time() == expected_end:
                    status = "OK"
                    reasons = ["LATEST_COMPLETED_BOUNDARY_PROVEN"]
                elif parsed.time() < expected_end:
                    status = "CURRENTNESS_UNVERIFIED"
                    reasons = ["EXPECTED_COMPLETED_BOUNDARY_NOT_REACHED"]
                else:
                    status = "CURRENTNESS_UNVERIFIED"
                    reasons = ["PROVIDER_TIMESTAMP_AHEAD_OF_EXPECTED_BOUNDARY"]
        else:
            # Intraday: the latest bar's calendar date matching the expected
            # trading date proves only that the bar belongs to today's
            # session, not that it reflects intraday progress within that
            # session -- date equality alone must not produce OK here.
            status = "CURRENTNESS_UNVERIFIED"
            reasons = ["INTRADAY_PROGRESS_NOT_PROVEN"]
    elif bar_date < expected_date:
        status = "STALE_OR_MISALIGNED"
        reasons = ["LATEST_BAR_BEFORE_EXPECTED_SESSION"]
    else:
        status = "STALE_OR_MISALIGNED"
        reasons = ["LATEST_BAR_AHEAD_OF_EXPECTED_SESSION"]

    return {
        "ok": status == "OK",
        "status": status,
        "symbol": symbol,
        "timeframe": timeframe,
        "snapshot_time": snapshot_time,
        "latest_bar_time": latest_bar_time,
        "expected_latest_trading_date": expected_date,
        "expected_trading_date_type": trading_day_map.get(expected_date),
        "session_phase": _us_session_phase(now_et),
        "now_et": now_et.isoformat(),
        "trading_calendar_source": "FUTU_OPEN_D",
        "reason_codes": reasons,
    }


@mcp.tool()
def data_health_check(symbol: str = "US.NVDA", timeframe: str = "15m"):
    """Single authoritative Data Health: trading calendar + session aware.

    Thin wrapper over _data_health_check_core, which contains the only
    freshness / stale / session / calendar rule in the system. The existing
    contract keys (ok, status, symbol, timeframe, snapshot_time,
    latest_bar_time) are preserved; all new fields are additive.
    """
    q = get_quote_ctx()

    try:
        return _data_health_check_core(q, symbol, timeframe)

    finally:
        q.close()


@mcp.tool()
def health_check():
    """Check whether Moomoo OpenD is reachable."""
    q = get_quote_ctx()

    try:
        ret, data = q.get_market_snapshot(["US.NVDA"])

        return {
            "ok": ret == RET_OK,
            "message": (
                "OpenD reachable"
                if ret == RET_OK
                else str(data)
            )
        }

    finally:
        q.close()




# ============================================================================
# D5.1 -- SuperTrend Engine v0.1 (frozen params)
#   ATR_PERIOD = 10, MULTIPLIER = 2.5, WARMUP_BARS = 20
#   Daily / 1H / 15m share one parameter set but compute independently.
#
# True Range (spec):
#   TR_0 = high_0 - low_0  (explicitly included in the ATR seed)
#   TR_t = max(high_t-low_t, |high_t-close_{t-1}|, |low_t-close_{t-1}|)
# Wilder ATR: seed at ARRAY INDEX N-1 (=9) = mean(TR_0..TR_9); thereafter
#   ATR_t = (ATR_{t-1}*(N-1) + TR_t)/N. No EMA / pandas ewm / TA-Lib.
# Final-band trail strictly uses Close_{t-1} (never Close_t).
# Internal seed at first ATR-computable point: BULLISH if Close>=HL2 else
# BEARISH; used only for recursion, never served externally before warmup.
# Flip (strict, mirrored): bull->bear only if Close_t < FinalLower_t;
#   bear->bull only if Close_t > FinalUpper_t. Close == band -> NO FLIP.
# prev_close = previous chronological valid bar close; NOT reset at session
#   boundaries (overnight / weekend gaps are captured by TR). No volume use.
# Session filtering is owned by the calling snapshot tool (existing bar /
#   timeframe authority); the pure builder consumes an already-causal series.
# ============================================================================

SUPERTREND_ATR_PERIOD = 10
SUPERTREND_MULTIPLIER = 2.5
SUPERTREND_WARMUP_BARS = 20
SUPERTREND_SCHEMA_VERSION = 1
SUPERTREND_STATES = ("BULLISH", "BEARISH", "INDETERMINATE")
SUPERTREND_FLIPS = ("BULLISH_FLIP", "BEARISH_FLIP", "NONE")
SUPERTREND_REASON_CODES = (
    "WARMUP_NOT_COMPLETE", "DATA_HEALTH_LIMITED",
    "CONFLICTING_DUPLICATE_TIMESTAMP", "INVALID_PRICE_DATA",
    "INSUFFICIENT_BARS", "SESSION_NOT_AVAILABLE",
)
SUPERTREND_CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "INDETERMINATE")


def _supertrend_validate_bars(bars):
    """Return (ordered_valid_rows, reason) for the pure engine.

    Each row must carry parseable, finite, positive OHLC with high>=low and
    low<=close<=high. Any invalid bar makes the whole run INDETERMINATE (no
    silent repair). Valid rows are NOT sorted here; callers supply causal
    (already time-ordered) bars. Duplicates are handled separately by the
    shared dedupe policy.
    """
    valid = []
    for row in bars or []:
        if not isinstance(row, dict):
            return [], "INVALID_PRICE_DATA"
        try:
            hh = float(row.get("high")); ll = float(row.get("low"))
            cc = float(row.get("close"))
        except (TypeError, ValueError, OverflowError):
            return [], "INVALID_PRICE_DATA"
        if not (math.isfinite(hh) and math.isfinite(ll) and math.isfinite(cc)):
            return [], "INVALID_PRICE_DATA"
        if not (hh > 0 and ll > 0 and cc > 0):
            return [], "INVALID_PRICE_DATA"
        if hh < ll or cc < ll or cc > hh:
            return [], "INVALID_PRICE_DATA"
        valid.append({"time_key": str(row.get("time_key")),
                      "high": hh, "low": ll, "close": cc})
    return valid, None


def build_supertrend_state(st_input):
    """Pure, deterministic SuperTrend builder (frozen ATR=10, mult=2.5, warmup=20).

    Input keys: generated_at, symbol, timeframe, bars (causal OHLC series),
    data_health. Official external state is only exposed once WARMUP_BARS(20)
    valid bars exist; before that internal numeric evidence may be present but
    state=INDETERMINATE / flip_event=NONE. Pure: no Moomoo, no runtime write,
    no AI, no account, no volume, no Regime/RS/Structure/SessionVWAP/AnchoredVWAP
    read, no positions/cost. Creates no overall_trend / confluence / score.
    """
    if not isinstance(st_input, dict):
        st_input = {}
    generated_at = st_input.get("generated_at")
    symbol = st_input.get("symbol")
    timeframe = st_input.get("timeframe")
    health = st_input.get("data_health") or {}
    health_ok = health.get("ok") is True and health.get("status") == "OK"
    N = SUPERTREND_ATR_PERIOD
    M = SUPERTREND_MULTIPLIER
    W = SUPERTREND_WARMUP_BARS

    def empty(reason):
        return clean_json_value({
            "schema_version": SUPERTREND_SCHEMA_VERSION,
            "generated_at": generated_at, "symbol": symbol,
            "timeframe": timeframe, "state": "INDETERMINATE",
            "supertrend_value": None, "final_upper": None, "final_lower": None,
            "atr": None, "atr_period": N, "multiplier": M,
            "distance_to_supertrend_pct": None, "flip_event": "NONE",
            "bars_used": 0, "warmup_required": W,
            "confidence": "INDETERMINATE", "reason_codes": [reason],
        })

    # ---- shared duplicate policy (identical dedupe / conflicting indet) ----
    raw_rows = st_input.get("bars")
    if not isinstance(raw_rows, list):
        raw_rows = []
    valid, vreason = _supertrend_validate_bars(raw_rows)
    if vreason:
        out = empty(vreason); out["bars_used"] = len(raw_rows); return out
    mapping, conflicting = _dedupe_bars_by_time(
        valid, fields=("high", "low", "close"))
    if conflicting:
        return empty("CONFLICTING_DUPLICATE_TIMESTAMP")
    # deterministic order (input is causal; we keep stable order by time_key)
    rows = []
    for key in sorted(mapping):
        hh, ll, cc = mapping[key]
        rows.append((key, hh, ll, cc))
    V = len(rows)
    if V == 0:
        return empty("INSUFFICIENT_BARS")
    warmup_done = V >= W

    highs = [r[1] for r in rows]
    lows = [r[2] for r in rows]
    closes = [r[3] for r in rows]

    # ---- True Range ----
    TR = [0.0] * V
    TR[0] = highs[0] - lows[0]
    for t in range(1, V):
        TR[t] = max(highs[t] - lows[t],
                    abs(highs[t] - closes[t - 1]),
                    abs(lows[t] - closes[t - 1]))

    # ---- Wilder ATR (seed at index N-1) ----
    atr = [None] * V
    if V >= N:
        atr[N - 1] = sum(TR[0:N]) / N
        for t in range(N, V):
            atr[t] = (atr[t - 1] * (N - 1) + TR[t]) / N

    # ---- Bands ----
    fup = [None] * V
    flo = [None] * V
    hl2 = [(highs[t] + lows[t]) / 2.0 for t in range(V)]
    d = [0] * V
    if V >= N:
        fup[N - 1] = hl2[N - 1] + M * atr[N - 1]
        flo[N - 1] = hl2[N - 1] - M * atr[N - 1]
        # internal seed (spec section 5): Close >= HL2 -> BULLISH else BEARISH
        d[N - 1] = 1 if closes[N - 1] >= hl2[N - 1] else -1
        for t in range(N, V):
            bu = hl2[t] + M * atr[t]
            bl = hl2[t] - M * atr[t]
            fup[t] = bu if (bu < fup[t - 1] or closes[t - 1] > fup[t - 1])                 else fup[t - 1]
            flo[t] = bl if (bl > flo[t - 1] or closes[t - 1] < flo[t - 1])                 else flo[t - 1]
            dd = d[t - 1]
            if dd == 1 and closes[t] < flo[t]:
                dd = -1
            elif dd == -1 and closes[t] > fup[t]:
                dd = 1
            d[t] = dd

    last_idx = V - 1
    internal_ok = V >= N
    int_state = None
    if internal_ok:
        int_state = d[last_idx]
    stval = None
    if internal_ok and int_state == 1:
        stval = flo[last_idx]
    elif internal_ok and int_state == -1:
        stval = fup[last_idx]

    # ---- flip_event (only meaningful for official state) ----
    flip_event = "NONE"
    if warmup_done and internal_ok and last_idx > N - 1 and d[last_idx] != d[last_idx - 1]:
        flip_event = "BULLISH_FLIP" if d[last_idx] == 1 else "BEARISH_FLIP"

    # ---- official state ----
    if not internal_ok:
        state = "INDETERMINATE"
    elif not warmup_done:
        state = "INDETERMINATE"
    else:
        state = "BULLISH" if int_state == 1 else "BEARISH"

    # ---- confidence: computation/data reliability only ----
    reasons = []
    if state == "INDETERMINATE":
        confidence = "INDETERMINATE"
        if V < N:
            reasons.append("INSUFFICIENT_BARS")
        elif not warmup_done:
            reasons.append("WARMUP_NOT_COMPLETE")
    else:
        confidence = "HIGH"
        if not health_ok:
            confidence = "MEDIUM"
            reasons.append("DATA_HEALTH_LIMITED")

    distance = None
    if stval is not None and stval > 0 and closes[last_idx] is not None:
        distance = round((closes[last_idx] - stval) / stval * 100.0, 4)

    atr_v = atr[last_idx] if internal_ok else None
    fup_v = fup[last_idx] if internal_ok else None
    flo_v = flo[last_idx] if internal_ok else None

    return clean_json_value({
        "schema_version": SUPERTREND_SCHEMA_VERSION,
        "generated_at": generated_at, "symbol": symbol,
        "timeframe": timeframe, "state": state,
        "supertrend_value": round(stval, 4) if stval is not None else None,
        "final_upper": round(fup_v, 4) if fup_v is not None else None,
        "final_lower": round(flo_v, 4) if flo_v is not None else None,
        "atr": round(atr_v, 4) if atr_v is not None else None,
        "atr_period": N, "multiplier": M,
        "distance_to_supertrend_pct": distance,
        "flip_event": flip_event if state != "INDETERMINATE" else "NONE",
        "bars_used": V, "warmup_required": W,
        "confidence": confidence,
        "reason_codes": sorted(set(reasons)),
    })


def _fetch_supertrend_bars_windowed(symbol, timeframe):
    """Fetch enough causal bars for the SuperTrend engine via existing get_bars.

    Intraday timeframes (1h/15m) keep only regular-session bars so the
    prev_close chain correctly carries overnight/weekend gaps (no per-session
    reset). Daily keeps all bars (one bar per trading day).
    """
    day_span = {"15m": 95, "1h": 95, "1d": 300, "day": 300}.get(timeframe, 95)
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=day_span)
    merged = {}
    cursor = start_dt
    intraday = timeframe in ("1h", "15m")
    step = (timedelta(days=23) if intraday else timedelta(days=120))
    while cursor < end_dt:
        win_end = min(cursor + step, end_dt)
        try:
            resp = get_bars(symbol, timeframe=timeframe,
                            start=cursor.strftime("%Y-%m-%d"),
                            end=win_end.strftime("%Y-%m-%d"), count=1000)
        except Exception:
            resp = {}
        data = (resp.get("data")
                if isinstance(resp, dict) and resp.get("ok") else [])
        for row in data or []:
            tk = row.get("time_key")
            if not isinstance(tk, str):
                continue
            if intraday and not _vwap_is_regular_bar_close(tk):
                continue
            merged[tk] = row
        cursor = win_end
    return [merged[k] for k in sorted(merged)]


@mcp.tool()
def get_supertrend_snapshot(symbol: str, timeframe: str = "1d"):
    """Read-only SuperTrend snapshot (frozen ATR=10, mult=2.5, warmup=20).

    Supports 1d / 1h / 15m (independent computation on shared params). Consumes
    Unified Data Health for freshness / data authority and fetches causal bars
    through the existing get_bars helper; intraday keeps regular-session bars
    only so overnight/weekend gaps are preserved. No volume, no positions, no
    AI, no runtime writes, no trading semantics.
    """
    generated_at = datetime.now().isoformat()
    health = data_health_check(symbol, timeframe=timeframe)
    if not isinstance(health, dict):
        health = {}
    bars = _fetch_supertrend_bars_windowed(symbol, timeframe)
    return build_supertrend_state({
        "generated_at": generated_at,
        "symbol": symbol,
        "timeframe": timeframe,
        "bars": bars,
        "data_health": health,
    })




# ============================================================================
# E1 -- Decision Envelope v0.1 (pure deterministic packager)
#   Reads ONLY already-frozen upstream outputs: Portfolio position context,
#   Unified Data Health, D1 Market Regime, D2 Relative Strength, D3 Price
#   Structure, D4.1 Session VWAP, D4.2 Anchored VWAP, D5 SuperTrend, plus an
#   optional analysis trigger (ANALYSIS_TRIGGER_ONLY). It NEVER recomputes any
#   of those modules, never reads/writes runtime, never calls AI, never sends
#   notifications, never opens trade contexts, and carries NO raw OHLCV/bars.
#
# Namespacing (addendum): each D1-D5 output lives in its own namespace as an
#   evidence object {source_module, source_schema_version, source_generated_at,
#   payload}. Nothing is shallow-merged or flattened and upstream state values
#   are passed through verbatim (no rename / reinterpretation).
#
# risk_flags = deterministic, single-source evidence INDEX only (sorted set for
#   canonical ordering; count/order carry no semantics). allowed_actions is a
#   fixed deterministic subset chosen solely from ai_mode and position
#   eligibility. Security: builder never accepts/emits account ids or secrets,
#   strips raw market-data keys, and the assembled payload is scanned at build
#   time (deterministic) for sensitive fields before returning.
# ============================================================================

E1_ENVELOPE_SCHEMA_VERSION = 1
E1_MODULES = ("market_regime", "relative_strength", "price_structure",
              "session_vwap", "anchored_vwap", "supertrend")
E1_ALLOWED_ACTIONS_ALL = ("HOLD", "WATCH", "ADD_CANDIDATE",
                          "REDUCE_CANDIDATE", "RISK_ALERT")
E1_ALLOWED_ACTIONS_NO_POSITION = ("HOLD", "WATCH", "ADD_CANDIDATE",
                                  "RISK_ALERT")
E1_ALLOWED_ACTIONS_DATA_QUALITY = ("WATCH", "RISK_ALERT")
E1_SENSITIVE_FIELDS = {
    "account_id", "accountid", "acc_id", "accid", "account_number",
    "api_key", "apikey", "secret", "secret_key", "token", "access_token",
    "authorization", "cookie", "trade_password", "password", "credential",
    "private_key",
}
E1_RAW_MARKET_FIELDS = {
    "bars", "candles", "candlestick", "candlesticks", "ticks", "tick",
    "order_book", "orderbook", "ohlc", "ohlcv", "raw_quotes", "raw_quote", "quotes",
    "raw", "historical_bars",
}

# Inline credential patterns matched against STRING VALUES anywhere in the
# payload (field-name stripping alone cannot protect non-sensitive keys whose
# values embed secrets). Matching values are redacted before serialization.
E1_TOKEN_VALUE_PATTERNS = (
    "api_key=", "apikey=", "authorization:", "bearer ", "secret=", "token=",
    "password=", "account_id=", "acc_id=", "trade_password=", "private_key=",
)


def _e1_clean(value):
    """Deterministic JSON-safe recursive clean (None preserved, dict order sorted)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_e1_clean(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _e1_clean(v) for k, v in sorted(value.items())}
    try:
        import math
        if isinstance(value, float):
            return value
    except Exception:
        pass
    return str(value)


def _e1_evidence(source_module, upstream):
    """Wrap one upstream D1-D5 payload verbatim with provenance (no flatten)."""
    if not isinstance(upstream, dict):
        upstream = {}
    return {
        "source_module": source_module,
        "source_schema_version": upstream.get("schema_version"),
        "source_generated_at": upstream.get("generated_at"),
        "payload": upstream,
    }


def _e1_strip_raw_market(value):
    """Recursively drop raw market-data containers and sensitive fields from the
    AI-facing payload (defense in depth; scan remains the black-box backstop)."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            nk = str(k).lower().replace("-", "_").replace(" ", "_")
            if nk in E1_RAW_MARKET_FIELDS:
                continue
            if nk in E1_SENSITIVE_FIELDS:
                continue
            out[str(k)] = _e1_strip_raw_market(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_e1_strip_raw_market(v) for v in value]
    return value


def _e1_sensitive_scan(value, _path=""):
    """Deterministic deep scan for sensitive field names / known identifiers."""
    hits = []
    if isinstance(value, dict):
        for k, v in value.items():
            nk = str(k).lower().replace("-", "_").replace(" ", "_")
            if nk in E1_SENSITIVE_FIELDS:
                hits.append(_path + "/" + str(k))
            # value that is a long digit run under an id-ish key
            if isinstance(v, str) and len(v) >= 9 and v.isdigit():
                hits.append(_path + "/" + str(k) + ":NUMBER")
            hits.extend(_e1_sensitive_scan(v, _path + "/" + str(k)))
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            hits.extend(_e1_sensitive_scan(v, f"{_path}[{i}]"))
    elif isinstance(value, str):
        low = value.lower()
        for token in ("api_key=", "apikey=", "authorization:", "bearer ",
                      "account_id=", "acc_id=", "secret=", "token="):
            if token in low:
                hits.append(_path + ":TOKEN")
    return sorted(set(hits))


def _e1_redact_sensitive_values(value):
    """Deterministic value-level redaction: any string whose content embeds a
    credential pattern is replaced with a placeholder BEFORE serialization so
    that raw secret values never appear in the final AI-facing payload."""
    if isinstance(value, str):
        low = value.lower()
        if any(pattern in low for pattern in E1_TOKEN_VALUE_PATTERNS):
            return "[REDACTED:SENSITIVE]"
        return value
    if isinstance(value, dict):
        return {str(k): _e1_redact_sensitive_values(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_e1_redact_sensitive_values(v) for v in value]
    return value


def _e1_redact_known_account(value, identifier):
    """Remove known account material from keys and values at every depth."""
    if isinstance(value, str):
        return value.replace(identifier, "[REDACTED:SENSITIVE]")
    if isinstance(value, dict):
        return {k: _e1_redact_known_account(v, identifier)
                for k, v in value.items() if identifier not in str(k)}
    if isinstance(value, (list, tuple)):
        return [_e1_redact_known_account(v, identifier) for v in value]
    if isinstance(value, (int, float)) and identifier in str(value):
        return "[REDACTED:SENSITIVE]"
    return value


def build_decision_envelope(env_input):
    """Pure deterministic Decision Envelope over frozen upstream outputs.

    Input keys (all optional except symbol/generated_at):
      generated_at, symbol, cycle_id, expected_cycle_time,
      position        - sanitized dict (quantity/cost_price/market_value/...)
      data_health     - Unified Data Health output (ok/status)
      market_regime, relative_strength, price_structure, session_vwap,
      anchored_vwap, supertrend  - the frozen D1-D5 payloads (verbatim)
      analysis_trigger - optional trigger event dict (ANALYSIS_TRIGGER_ONLY)
      evidence_cycle_ids - optional dict {module: cycle_id}; SAME_CYCLE is
          granted ONLY when every evidence module maps to the assembly cycle_id
          (explicit orchestration identity). Timestamps never imply cycle.

    Pure: no I/O, network, AI, notification, runtime write or trade call. All
    outputs are canonical JSON. risk_flags are a single-source evidence index.
    """
    if not isinstance(env_input, dict):
        env_input = {}
    generated_at = env_input.get("generated_at")
    symbol = env_input.get("symbol")
    cycle_id = env_input.get("cycle_id")
    expected_cycle_time = env_input.get("expected_cycle_time")

    def norm():
        health = env_input.get("data_health")
        health = health if isinstance(health, dict) else {}
        health_ok = health.get("ok") is True and health.get("status") == "OK"
        ai_mode = "MARKET_ANALYSIS" if health_ok else "DATA_QUALITY_ONLY"

        # ---- position context (context only; never affects D1-D5 evidence) ----
        position = env_input.get("position")
        position = position if isinstance(position, dict) else {}
        quantity = position.get("quantity")
        try:
            qty = float(quantity) if quantity is not None else 0.0
        except (TypeError, ValueError):
            qty = 0.0
        is_existing = qty > 0.0
        position_context = {
            "is_existing_position": is_existing,
            "quantity": quantity if quantity is not None else None,
            "cost_basis": position.get("cost_price", position.get("cost_basis")),
            "market_value": position.get("market_value"),
            "market_price": position.get("market_price"),
        }

        # ---- data health (authority only; no re-derivation) ----
        data_health = {
            "status": health.get("status"),
            "latest_times": _e1_clean(health.get("latest_times")),
            "timeframes": _e1_clean(health.get("timeframes")),
            "reason_codes": sorted(set(health.get("reason_codes") or [])),
            "authority": "data_health_check",
        }

        # ---- D1/D2 market context namespaces ----
        regime_ev = _e1_evidence("market_regime", env_input.get("market_regime"))
        rs_ev = _e1_evidence("relative_strength", env_input.get("relative_strength"))
        market_context = {"regime": regime_ev, "relative_strength": rs_ev}

        # ---- D3/D4.1/D4.2/D5 technical namespaces ----
        tech = {}
        for mod, key in (("price_structure", "price_structure"),
                         ("session_vwap", "session_vwap"),
                         ("anchored_vwap", "anchored_vwap"),
                         ("supertrend", "supertrend")):
            tech[mod] = _e1_evidence(mod, env_input.get(key))
        technical_evidence = {
            "price_structure": tech["price_structure"],
            "session_vwap": tech["session_vwap"],
            "anchored_vwap": tech["anchored_vwap"],
            "supertrend": tech["supertrend"],
        }

        # ---- risk flags (single-source explicit mapping, canonical) ----
        flags = []
        if not health_ok:
            flags.append("DATA_HEALTH_ABNORMAL")
        st_payload = env_input.get("price_structure") or {}
        d3_vals = []
        for f in ("primary_structure", "current_phase", "structure_integrity"):
            v = st_payload.get(f)
            if isinstance(v, str):
                d3_vals.append(v)
        if any(x in ("STRUCTURE_DAMAGED", "DAMAGED", "BROKEN")
               for x in d3_vals):
            flags.append("STRUCTURE_DAMAGED")
        rs_payload = env_input.get("relative_strength") or {}
        rs_tok = (str(rs_payload.get("state", "")) + "|"
                  + str(rs_payload.get("relative_direction", "")))
        if "DETERIOR" in rs_tok.upper() or "WEAKEN" in rs_tok.upper():
            flags.append("RS_DETERIORATING")
        sv_payload = env_input.get("session_vwap") or {}
        if sv_payload.get("price_position") == "BELOW_VWAP":
            flags.append("BELOW_SESSION_VWAP")
        av_payload = env_input.get("anchored_vwap") or {}
        anchors = av_payload.get("anchors")
        low_slot = None
        if isinstance(anchors, dict):
            low_slot = anchors.get("latest_swing_low")
        if isinstance(low_slot, dict)                 and low_slot.get("price_position") == "BELOW_AVWAP":
            flags.append("BELOW_SWING_LOW_AVWAP")
        st5 = env_input.get("supertrend") or {}
        if st5.get("state") == "BEARISH":
            flags.append("SUPERTREND_BEARISH")
        if st5.get("flip_event") == "BEARISH_FLIP":
            flags.append("SUPERTREND_BEARISH_FLIP")
        risk_flags = sorted(set(flags))

        # ---- allowed actions (deterministic subset) ----
        if ai_mode == "DATA_QUALITY_ONLY":
            allowed_actions = list(E1_ALLOWED_ACTIONS_DATA_QUALITY)
        elif is_existing:
            allowed_actions = list(E1_ALLOWED_ACTIONS_ALL)
        else:
            allowed_actions = list(E1_ALLOWED_ACTIONS_NO_POSITION)

        # ---- analysis trigger (never fabricated) ----
        trig = env_input.get("analysis_trigger")
        analysis_trigger = None
        if isinstance(trig, dict) and trig:
            analysis_trigger = {
                "semantic_role": "ANALYSIS_TRIGGER_ONLY",
                "event_type": trig.get("event_type"),
                "severity": trig.get("severity"),
                "fingerprint": trig.get("fingerprint"),
                "previous_state": trig.get("previous_state"),
                "current_state": trig.get("current_state"),
            }

        # ---- assembly context (cycle identity authority ONLY) ----
        # SAME_CYCLE is derived exclusively from explicit orchestration cycle
        # identity: an assembly cycle_id plus an evidence_cycle_ids mapping in
        # which EVERY evidence module carries the SAME cycle_id. Timestamps
        # (source_generated_at / expected_cycle_time) are audit fields only and
        # are NEVER used to infer cycle membership; Unified Data Health remains
        # the single freshness authority. Missing/mixed cycle provenance =>
        # UNVERIFIED.
        evidence_cycle_ids = env_input.get("evidence_cycle_ids")
        cycle_ok = False
        if isinstance(cycle_id, str) and isinstance(evidence_cycle_ids, dict):
            mods = ("market_regime", "relative_strength", "price_structure",
                    "session_vwap", "anchored_vwap", "supertrend")
            if all(isinstance(evidence_cycle_ids.get(m), str)
                   and evidence_cycle_ids.get(m) == cycle_id for m in mods):
                cycle_ok = True
        sync = "SAME_CYCLE" if cycle_ok else "UNVERIFIED"
        assembly_context = {
            "cycle_id": cycle_id,
            "assembled_at": generated_at,
            "evidence_sync_status": sync,
        }

        envelope = {
            "schema_version": E1_ENVELOPE_SCHEMA_VERSION,
            "symbol": symbol,
            "generated_at": generated_at,
            "position_context": position_context,
            "data_health": data_health,
            "market_context": market_context,
            "technical_evidence": technical_evidence,
            "trigger_context": None,
            "analysis_trigger": analysis_trigger,
            "assembly_context": assembly_context,
            "risk_flags": risk_flags,
            "allowed_actions": allowed_actions,
            "ai_mode": ai_mode,
        }
        # strip raw market arrays + sensitive FIELDS, then VALUE-redact any
        # inline credential patterns, then clean, then scan the final payload
        envelope = _e1_strip_raw_market(envelope)
        envelope = _e1_redact_sensitive_values(envelope)
        envelope = _e1_clean(envelope)
        # Scan serialized values too: a known account can appear under any key.
        identifier = str(require_primary_us_account_id())
        account_hit = bool(identifier) and identifier in json.dumps(envelope)
        if account_hit:
            envelope = _e1_redact_known_account(envelope, identifier)
        # black-box deterministic security scan (reports path/type only)
        hits = _e1_sensitive_scan(envelope)
        if account_hit:
            hits = sorted(set(hits + ["KNOWN_ACCOUNT_IDENTIFIER"]))
        blocked = len(hits) > 0
        envelope["security_scan"] = {
            "blocked": blocked,
            "findings": hits,
        }
        if blocked:
            envelope["allowed_actions"] = list(E1_ALLOWED_ACTIONS_DATA_QUALITY)
            envelope["risk_flags"] = sorted(
                set(risk_flags + ["SECURITY_SCAN_BLOCKED"]))
        if identifier and identifier in json.dumps(envelope):
            raise ValueError("Known account identifier remains in decision envelope")
        return envelope

    return norm()


def assemble_decision_envelope(symbol: str, count: int = 120):
    """Read-only real assembly: call the frozen D1-D5 snapshot tools + Unified
    Data Health + sanitized position context, then build the envelope. No AI,
    no notification, no trading, no runtime writes."""
    generated_at = datetime.now().isoformat()
    regime = get_market_regime_snapshot(count=count)
    rs = get_relative_strength_snapshot(symbol=symbol, count=count)
    structure = get_price_structure_snapshot(symbol=symbol, count=count)
    session_vwap = get_session_vwap_snapshot(symbol=symbol, count=count)
    anchored_vwap = get_anchored_vwap_snapshot(symbol=symbol)
    supertrend = get_supertrend_snapshot(symbol=symbol, timeframe="1d")
    health = data_health_check(symbol=symbol, timeframe="15m")

    position = None
    try:
        pf = get_portfolio_state(require_primary_us_account_id())
    except Exception:
        pf = {}
    if isinstance(pf, dict) and pf.get("ok"):
        for p in pf.get("positions", []) or []:
            if p.get("symbol") == symbol:
                position = {
                    "quantity": p.get("quantity"),
                    "cost_price": p.get("cost_price"),
                    "market_price": p.get("market_price"),
                    "market_value": p.get("market_value"),
                }
                break
    if not isinstance(health, dict):
        health = {}
    return build_decision_envelope({
        "generated_at": generated_at,
        "symbol": symbol,
        "cycle_id": None,
        "position": position,
        "data_health": health,
        "market_regime": regime if isinstance(regime, dict) else {},
        "relative_strength": rs if isinstance(rs, dict) else {},
        "price_structure": structure if isinstance(structure, dict) else {},
        "session_vwap": session_vwap if isinstance(session_vwap, dict) else {},
        "anchored_vwap": anchored_vwap if isinstance(anchored_vwap, dict) else {},
        "supertrend": supertrend if isinstance(supertrend, dict) else {},
        "analysis_trigger": None,
        "expected_cycle_time": None,
    })


@mcp.tool()
def get_decision_envelope_snapshot(symbol: str, count: int = 120):
    """Read-only Decision Envelope for one symbol (D1-D5 frozen authorities)."""
    return assemble_decision_envelope(symbol=symbol, count=count)




# ============================================================================
# E2 -- Notification Policy v0.1 (pure deterministic intent builder)
#
#   E2 NEVER sends Discord / Email / Slack / push / toast, never calls AI,
#   never trades, never writes runtime/files, and never recomputes D1-D5,
#   risk severity, Data Health, cooldown, dedup or AI decisions. It only
#   consumes upstream authorities and emits a deterministic Notification
#   Intent (delivery_policy in {NOTIFY_NOW, JOURNAL_ONLY, SUPPRESS}).
#
#   Authority separation (Design Authority Addendum):
#     severity authority            = Trigger Engine  (input `severity`)
#     AI response availability      = Orchestration layer (input
#                                     `ai_response_status`; E2 NEVER infers it
#                                     from requests/skipped/objects/timestamps)
#     freshness authority           = Unified Data Health (via E1 ai_mode only)
#     decision_state authority      = validated Common AI Response
#     delivery authority            = this E2 policy
#
#   Pairing authority: when ai_response_status == PRESENT the paired request
#   identity (request_id + pairing_symbol + pairing_cycle_id, supplied by the
#   orchestration layer) must strictly match the response request_id and the
#   E1 envelope symbol / assembly cycle_id. No fuzzy matching.
#
#   SUPPLESS is never deletion: original severity, fingerprint, cycle_id,
#   request_id and a suppression reason are always retained.
# ============================================================================

E2_NOTIFICATION_SCHEMA_VERSION = 1
E2_AI_RESPONSE_STATUSES = ("PRESENT", "NOT_REQUESTED", "PENDING", "FAILED")
E2_SEVERITIES = ("HIGH", "MEDIUM", "LOW")
E2_CATEGORIES = ("MARKET_EVENT", "DATA_QUALITY_EVENT")
E2_CHANNELS = ("DISCORD", "NONE")
E2_FALLBACKS = ("EMAIL_ON_PRIMARY_FAILURE", "NONE")
E2_REASON_AI_NOT_REQUESTED = "AI_NOT_REQUESTED"
E2_REASON_AI_RESPONSE_PENDING = "AI_RESPONSE_PENDING"
E2_REASON_AI_RESPONSE_FAILED = "AI_RESPONSE_FAILED"
E2_REASON_AI_DECISION_NOT_ALLOWED = "AI_DECISION_NOT_ALLOWED"
E2_REASON_INVALID_INPUT = "INVALID_INPUT"
E2_DQ_RATIONALE = (
    "DATA_QUALITY_EVENT (deterministic Data Health signal; "
    "not a market-direction judgment)."
)

# User-facing DATA_QUALITY_EVENT notifications may only expose flags that are
# data / security-integrity in nature (Data Quality Semantic Isolation
# Addendum section 4). Market-judgment flags must never become DQ message
# semantics; the complete E1 flag list is retained only in audit_context.
E2_DQ_USER_FACING_RISK_FLAGS = {"DATA_HEALTH_ABNORMAL"}


def _e2_matrix(severity):
    """Deterministic base delivery matrix (identical semantics for MARKET and
    DATA_QUALITY events; HIGH/MEDIUM/LOW map to NOTIFY_NOW..JOURNAL_ONLY)."""
    if severity == "HIGH":
        return "NOTIFY_NOW", "DISCORD", "EMAIL_ON_PRIMARY_FAILURE"
    if severity == "MEDIUM":
        return "NOTIFY_NOW", "DISCORD", "NONE"
    return "JOURNAL_ONLY", "NONE", "NONE"


def _e2_verified_response(intent_input, envelope, request_id):
    """Strict pairing verification for a PRESENT Common AI Response.

    Returns (response_dict, ok_bool). Not ok => the event is treated as
    FAILED (AI_RESPONSE_FAILED) -- never auto-corrected."""
    response = intent_input.get("ai_response")
    if not isinstance(response, dict):
        return None, False
    validation = validate_ai_response(response)
    if not validation.get("ok"):
        return None, False
    if not (isinstance(request_id, str)
            and isinstance(response.get("request_id"), str)
            and response.get("request_id") == request_id):
        return None, False
    pairing_symbol = intent_input.get("pairing_symbol")
    if pairing_symbol is not None and pairing_symbol != envelope.get("symbol"):
        return None, False
    pairing_cycle = intent_input.get("pairing_cycle_id")
    env_cycle = None
    assembly = envelope.get("assembly_context")
    if isinstance(assembly, dict):
        env_cycle = assembly.get("cycle_id")
    if pairing_cycle is not None:
        if env_cycle is None or pairing_cycle != env_cycle:
            return None, False
    return response, True


def build_notification_intent(intent_input):
    """Pure, deterministic Notification Policy builder -> Notification Intent.

    Input contract (all authorities passed in, never derived):
      created_at          - clock field (the ONLY nondeterministic output)
      envelope            - E1 Decision Envelope dict (required)
      severity            - Trigger authority verbatim: HIGH/MEDIUM/LOW
      fingerprint         - upstream dedup fingerprint (pass-through)
      dedup_eligible      - upstream bool (default True; not recomputed here)
      cooldown_eligible   - upstream bool (default True; not recomputed here)
      suppression_reason  - upstream dedup/cooldown reason (verbatim)
      invocation_reason   - Invocation Gate reason (verbatim, preserved, not
                            reinterpreted: LOW_SEVERITY_ONLY / DATA_HEALTH_
                            BLOCKED / INVALID_ANALYSIS_STATE / ...)
      ai_response_status  - orchestration authority: PRESENT / NOT_REQUESTED /
                            PENDING / FAILED  (NEVER inferred)
      ai_response         - validated Common AI Response (used when PRESENT)
      request_id          - paired request identity (orchestration authority)
      pairing_symbol      - expected symbol of the paired request
      pairing_cycle_id    - expected assembly cycle of the paired request

    Pure: no network, no Discord/Email send, no AI, no runtime/file write, no
    trade. SUPPRESS always retains severity / fingerprint / cycle / request /
    reason. Final intent is re-scanned and value-redacted before return.
    """
    if not isinstance(intent_input, dict):
        intent_input = {}
    created_at = intent_input.get("created_at")
    envelope = intent_input.get("envelope")
    envelope = envelope if isinstance(envelope, dict) else {}
    severity = intent_input.get("severity")
    ai_status = intent_input.get("ai_response_status")
    symbol = envelope.get("symbol")
    if severity not in E2_SEVERITIES or ai_status not in E2_AI_RESPONSE_STATUSES:
        # defensive guard: never crash; deterministic SUPPRESS fallback
        base = {
            "schema_version": E2_NOTIFICATION_SCHEMA_VERSION,
            "symbol": symbol if isinstance(symbol, str) else None,
            "created_at": created_at,
            "notification_category": None,
            "delivery_policy": "SUPPRESS",
            "severity": severity if severity in E2_SEVERITIES else None,
            "decision_state": None,
            "primary_channel": "NONE",
            "fallback_policy": "NONE",
            "dedup_context": {
                "fingerprint": intent_input.get("fingerprint"),
                "eligible": False,
                "suppression_reason": E2_REASON_INVALID_INPUT,
            },
            "message_context": {
                "headline_fields": {
                    "symbol": symbol if isinstance(symbol, str) else None,
                    "severity": severity if severity in E2_SEVERITIES else None,
                    "decision_state": None,
                    "category": None,
                },
                "short_rationale": None,
                "risk_flags": [],
            },
            "source": {
                "decision_envelope_schema": envelope.get("schema_version"),
                "ai_response_schema": None,
                "cycle_id": None,
            },
            "security_context": {"sanitized": True, "findings": []},
            "reason": E2_REASON_INVALID_INPUT,
            "ai_response_status": ai_status
            if ai_status in E2_AI_RESPONSE_STATUSES else None,
            "request_id": intent_input.get("request_id"),
            "invocation_reason": intent_input.get("invocation_reason"),
        }
        return _e2_finalize(base)

    ai_mode = envelope.get("ai_mode")
    if ai_mode == "MARKET_ANALYSIS":
        category = "MARKET_EVENT"
    elif ai_mode == "DATA_QUALITY_ONLY":
        category = "DATA_QUALITY_EVENT"
    else:
        category = None

    assembly = envelope.get("assembly_context")
    assembly = assembly if isinstance(assembly, dict) else {}
    cycle_id = assembly.get("cycle_id")
    request_id = intent_input.get("request_id")
    fingerprint = intent_input.get("fingerprint")
    invocation_reason = intent_input.get("invocation_reason")
    dedup_eligible = bool(intent_input.get("dedup_eligible", True))
    cooldown_eligible = bool(intent_input.get("cooldown_eligible", True))
    upstream_suppression = intent_input.get("suppression_reason")
    allowed = envelope.get("allowed_actions")
    allowed = set(allowed) if isinstance(allowed, list) else set()
    env_risk_flags = envelope.get("risk_flags")
    env_risk_flags = sorted(
        set(env_risk_flags)) if isinstance(env_risk_flags, list) else []
    env_schema = envelope.get("schema_version")

    # ---- intent skeleton fields set per branch ----
    policy = None
    primary = "NONE"
    fallback = "NONE"
    reason = None
    decision = None
    resp_schema = None
    rationale = None
    suppression = upstream_suppression

    eligible = dedup_eligible and cooldown_eligible
    if not eligible:
        # upstream dedup/cooldown blocked -> deterministic SUPPRESS
        policy = "SUPPRESS"
        suppression = upstream_suppression if isinstance(
            upstream_suppression, str) else None
    elif category == "MARKET_EVENT":
        if ai_status == "PRESENT":
            response, ok = _e2_verified_response(
                intent_input, envelope, request_id)
            if not ok:
                policy = "SUPPRESS"
                reason = E2_REASON_AI_RESPONSE_FAILED
            else:
                cand = response.get("decision_state")
                if cand not in allowed:
                    policy = "SUPPRESS"
                    reason = E2_REASON_AI_DECISION_NOT_ALLOWED
                else:
                    decision = cand
                    resp_schema = response.get("schema_version")
                    policy, primary, fallback = _e2_matrix(severity)
                    rationale = response.get("short_rationale")
        elif ai_status == "NOT_REQUESTED":
            policy = "JOURNAL_ONLY"
            reason = E2_REASON_AI_NOT_REQUESTED
        elif ai_status == "PENDING":
            policy = "SUPPRESS"
            reason = E2_REASON_AI_RESPONSE_PENDING
        else:  # FAILED
            policy = "SUPPRESS"
            reason = E2_REASON_AI_RESPONSE_FAILED
    else:  # DATA_QUALITY_EVENT -- no AI response required
        # DQ semantic isolation: the Common AI decision_state and short
        # rationale NEVER enter the user-visible intent, regardless of
        # ai_response_status (Addendum sections 2-3, 7). ai_response_status
        # remains top-level audit metadata and never affects decision /
        # rationale / delivery matrix.
        policy, primary, fallback = _e2_matrix(severity)
        rationale = E2_DQ_RATIONALE
        if ai_status == "PRESENT":
            response, ok = _e2_verified_response(
                intent_input, envelope, request_id)
            if ok:
                # audit-only provenance: response schema retained; the model
                # decision / rationale are deliberately dropped
                resp_schema = response.get("schema_version")

    # user-facing flag allowlist: MARKET_EVENT passes the full E1 risk_flags
    # index; a DATA_QUALITY_EVENT message exposes only data/security-integrity
    # flags (Addendum section 4). Full flags remain in audit_context only.
    if category == "DATA_QUALITY_EVENT":
        user_risk_flags = [
            flag for flag in env_risk_flags
            if flag in E2_DQ_USER_FACING_RISK_FLAGS
        ]
    else:
        user_risk_flags = env_risk_flags

    intent = {
        "schema_version": E2_NOTIFICATION_SCHEMA_VERSION,
        "symbol": symbol,
        "created_at": created_at,
        "notification_category": category,
        "delivery_policy": policy,
        "severity": severity,
        "decision_state": decision,
        "primary_channel": primary,
        "fallback_policy": fallback,
        "dedup_context": {
            "fingerprint": fingerprint,
            "eligible": eligible,
            "suppression_reason": suppression,
        },
        "message_context": {
            "headline_fields": {
                "symbol": symbol,
                "severity": severity,
                "decision_state": decision,
                "category": category,
            },
            "short_rationale": rationale,
            "risk_flags": user_risk_flags,
        },
        "source": {
            "decision_envelope_schema": env_schema,
            "ai_response_schema": resp_schema,
            "cycle_id": cycle_id,
        },
        "security_context": {"sanitized": True, "findings": []},
        "audit_context": {"risk_flags_full": env_risk_flags},
        "reason": reason,
        "ai_response_status": ai_status,
        "request_id": request_id,
        "invocation_reason": invocation_reason,
    }
    return _e2_finalize(intent)


def _e2_finalize(intent):
    """Deterministic canonicalization + transport-facing security pass.

    Strips raw market arrays / sensitive fields, value-redacts inline
    credential patterns, canonical-sorts, then black-box scans. The scan only
    reports paths/types (never values)."""
    intent = _e1_strip_raw_market(intent)
    intent = _e1_redact_sensitive_values(intent)
    intent = _e1_clean(intent)
    hits = _e1_sensitive_scan(intent)
    intent["security_context"] = {
        "sanitized": True,
        "findings": hits,
    }
    return intent




# ============================================================================
# E3 -- Discord / Email Notification Transport v0.1
#
#   E3 renders + sends + falls back + returns a delivery result. It makes NO
#   market judgment, consumes ONLY an E2 Notification Intent (never D1-D5 /
#   E1 raw envelope / bars / portfolio raw), strictly obeys the E2
#   delivery_policy, and never modifies severity / decision_state /
#   notification_category / risk_flags / short_rationale.
#
#   Authorities:
#     delivery_policy  (E2)   -> NOTIFY_NOW alone may send; JOURNAL_ONLY and
#                                SUPPRESS never send.
#     credentials            -> environment variables ONLY (Windows user env
#                                via load_windows_user_env + os.environ). No
#                                hard-coded URL / token / secret anywhere.
#     fallback               -> email attempted ONLY when
#                                fallback_policy == EMAIL_ON_PRIMARY_FAILURE
#                                AND Discord primary FAILED.
#
#   Purity: render_notification_message is pure + deterministic. Transport
#   functions use a single attempt (no retry policy), bounded timeouts and
#   sanitized errors. No AI, no trading, no portfolio mutation, no runtime
#   writes. Live sends are NOT performed by default.
# ============================================================================

E3_DELIVERY_RESULT_SCHEMA_VERSION = 1
E3_WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
E3_SMTP_HOST_ENV = "EMAIL_SMTP_HOST"
E3_SMTP_PORT_ENV = "EMAIL_SMTP_PORT"
E3_SMTP_USER_ENV = "EMAIL_SMTP_USER"
E3_SMTP_PASSWORD_ENV = "EMAIL_SMTP_PASSWORD"
E3_EMAIL_FROM_ENV = "EMAIL_FROM"
E3_EMAIL_TO_ENV = "EMAIL_TO"
E3_DISCORD_TIMEOUT_SECONDS = 10.0
E3_SMTP_TIMEOUT_SECONDS = 15.0
E3_DELIVERY_POLICIES = ("NOTIFY_NOW", "JOURNAL_ONLY", "SUPPRESS")


def _e3_sanitize_transport_error(category, status_code=None, detail=None):
    """Deterministic sanitized error record: type/category + status code + a
    safe short detail. NEVER contains URLs, headers, bodies or credentials."""
    safe_detail = "TRANSPORT_ERROR"
    if isinstance(detail, str):
        # keep only the exception class-ish token / generic phrasing
        safe_detail = "TRANSPORT_EXCEPTION"
    return {
        "category": category,
        "status_code": status_code,
        "message": safe_detail,
    }


def render_notification_message(intent):
    """Pure deterministic renderer -> {subject, body, category, timestamp}.

    Uses ONLY user-facing fields from the E2 intent (symbol, severity,
    decision_state, notification_category, message_context.short_rationale and
    message_context.risk_flags). Never renders audit_context, source payload,
    the full envelope, security internals, raw arrays or account identifiers.
    MARKET events may show decision_state; DATA_QUALITY_EVENT messages never
    show decision_state / AI rationale / market risk flags (E2 has already
    isolated these)."""
    if not isinstance(intent, dict):
        intent = {}
    symbol = intent.get("symbol")
    severity = intent.get("severity")
    category = intent.get("notification_category")
    decision = intent.get("decision_state")
    mc = intent.get("message_context")
    mc = mc if isinstance(mc, dict) else {}
    rationale = mc.get("short_rationale")
    flags = mc.get("risk_flags")
    flags = sorted(set(flags)) if isinstance(flags, list) else []
    created = intent.get("created_at")

    if category == "DATA_QUALITY_EVENT":
        # DQ template: no decision_state / AI rationale / market flags
        subject_parts = [symbol, severity, "DATA_QUALITY_EVENT"]
        lines = []
        if symbol is not None:
            lines.append("symbol: %s" % symbol)
        if severity is not None:
            lines.append("severity: %s" % severity)
        lines.append("category: DATA_QUALITY_EVENT")
        if isinstance(rationale, str) and rationale:
            lines.append("rationale: %s" % rationale)
        if flags:
            lines.append("risk_flags: %s" % ", ".join(flags))
        if isinstance(created, str):
            lines.append("timestamp: %s" % created)
        return {
            "subject": " | ".join(str(p) for p in subject_parts if p is not None),
            "body": "\n".join(lines),
            "category": "DATA_QUALITY_EVENT",
            "timestamp": created,
        }
    # MARKET template (default)
    subject_parts = [symbol, severity]
    if decision is not None:
        subject_parts.append(decision)
    if category is not None:
        subject_parts.append(category)
    lines = []
    if symbol is not None:
        lines.append("symbol: %s" % symbol)
    if severity is not None:
        lines.append("severity: %s" % severity)
    if decision is not None:
        lines.append("decision_state: %s" % decision)
    if category is not None:
        lines.append("category: %s" % category)
    if isinstance(rationale, str) and rationale:
        lines.append("rationale: %s" % rationale)
    if flags:
        lines.append("risk_flags: %s" % ", ".join(flags))
    if isinstance(created, str):
        lines.append("timestamp: %s" % created)
    return {
        "subject": " | ".join(str(p) for p in subject_parts if p is not None),
        "body": "\n".join(lines),
        "category": category,
        "timestamp": created,
    }


def _e3_webhook_url():
    load_windows_user_env(E3_WEBHOOK_ENV)
    url = os.environ.get(E3_WEBHOOK_ENV)
    if isinstance(url, str) and url.strip():
        return url.strip()
    return None


def send_discord_message(content, webhook_url=None, timeout=E3_DISCORD_TIMEOUT_SECONDS,
                         _urlopen=None):
    """Single-attempt Discord webhook POST via stdlib urllib.

    webhook_url comes from the environment when not supplied (tests inject
    mocks). Returns (ok, error_record). No retry policy. Errors sanitized."""
    url = webhook_url
    if url is None:
        url = _e3_webhook_url()
    if not isinstance(url, str) or not url.strip():
        return False, _e3_sanitize_transport_error("DISCORD_NOT_CONFIGURED")
    try:
        import json as _json
        import urllib.request as _urlreq
        import urllib.error as _urlerr
        payload = _json.dumps({"content": content}).encode("utf-8")
        req = _urlreq.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "StockRadar-NotificationTransport/0.1"},
            method="POST",
        )
        opener = _urlopen if _urlopen is not None else _urlreq.urlopen
        try:
            with opener(req, timeout=timeout) as resp:
                code = resp.getcode() if hasattr(resp, "getcode") else 200
                resp.read(1024)
        except _urlerr.HTTPError as exc:
            # E3.2 hotfix: urllib raises HTTPError for 4xx/5xx. Classify with
            # its status code instead of the generic exception bucket. The
            # response body / URL are NEVER read or recorded (security).
            code = exc.code
            if isinstance(code, int) and 200 <= code < 300:
                return True, None
            return False, _e3_sanitize_transport_error(
                "DISCORD_HTTP_ERROR", status_code=code)
        if isinstance(code, int) and 200 <= code < 300:
            return True, None
        return False, _e3_sanitize_transport_error(
            "DISCORD_HTTP_ERROR", status_code=code)
    except Exception as exc:
        return False, _e3_sanitize_transport_error("DISCORD_EXCEPTION",
                                                   detail=type(exc).__name__)


def _e3_email_config():
    cfg = {}
    for env_name, key in ((E3_SMTP_HOST_ENV, "host"),
                          (E3_SMTP_PORT_ENV, "port"),
                          (E3_SMTP_USER_ENV, "user"),
                          (E3_SMTP_PASSWORD_ENV, "password"),
                          (E3_EMAIL_FROM_ENV, "from_addr"),
                          (E3_EMAIL_TO_ENV, "to_addr")):
        load_windows_user_env(env_name)
        value = os.environ.get(env_name)
        cfg[key] = value.strip() if isinstance(value, str) else None
    return cfg


def send_email_fallback(subject, body, email_config=None,
                        timeout=E3_SMTP_TIMEOUT_SECONDS, _sendfunc=None):
    """Single-attempt Email fallback via smtplib (stdlib).

    Only called when E2 explicitly allows fallback. Credentials come from the
    environment unless overridden for tests. Returns (ok, error_record)."""
    cfg = email_config if isinstance(email_config, dict) else {}
    if not cfg:
        cfg = _e3_email_config()
    host = cfg.get("host")
    to_addr = cfg.get("to_addr")
    from_addr = cfg.get("from_addr")
    if not (isinstance(host, str) and host
            and isinstance(to_addr, str) and to_addr):
        return False, _e3_sanitize_transport_error("EMAIL_NOT_CONFIGURED")
    try:
        if _sendfunc is not None:
            ok, err = _sendfunc(cfg, subject, body, timeout)
            return ok, err
        import smtplib
        from email.mime.text import MIMEText
        port = int(cfg.get("port") or 587)
        user = cfg.get("user")
        password = cfg.get("password")
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_addr if from_addr else user
        msg["To"] = to_addr
        server = smtplib.SMTP(host, port, timeout=timeout)
        try:
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls()
                server.ehlo()
            if user and password:
                server.login(user, password)
            server.sendmail(msg["From"], [to_addr], msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return True, None
    except Exception as exc:
        return False, _e3_sanitize_transport_error("EMAIL_EXCEPTION",
                                                   detail=type(exc).__name__)


def send_notification(intent, discord_webhook_url=None, email_config=None,
                      transport=None):
    """Orchestrate one E2 Notification Intent -> Delivery Result.

    delivery_policy authority (E2) is strictly obeyed:
      NOTIFY_NOW    -> primary channel (DISCORD) attempted; email fallback
                       ONLY when fallback_policy == EMAIL_ON_PRIMARY_FAILURE
                       and Discord FAILED; email never after Discord success.
      JOURNAL_ONLY / SUPPRESS -> NOT_SENT, never sent regardless of severity.
    Single attempt per transport (no retry). No runtime write, no AI, no
    trading. Input intent is never mutated; semantic fields are preserved in
    the result.
    """
    if not isinstance(intent, dict):
        intent = {}
    symbol = intent.get("symbol")
    policy = intent.get("delivery_policy")
    severity = intent.get("severity")
    decision = intent.get("decision_state")
    category = intent.get("notification_category")
    mc = intent.get("message_context")
    mc = mc if isinstance(mc, dict) else {}
    flags = sorted(set(mc.get("risk_flags"))) if isinstance(mc.get("risk_flags"), list) else []
    rationale = mc.get("short_rationale")
    fingerprint = None
    dc = intent.get("dedup_context")
    if isinstance(dc, dict):
        fingerprint = dc.get("fingerprint")
    cycle_id = None
    src = intent.get("source")
    if isinstance(src, dict):
        cycle_id = src.get("cycle_id")
    reason = intent.get("reason")
    primary_channel = intent.get("primary_channel")
    fallback_policy = intent.get("fallback_policy")
    attempted_at = datetime.now().isoformat()

    transport = transport if isinstance(transport, dict) else {}
    discord_fn = transport.get("discord") if callable(transport.get("discord")) else None
    email_fn = transport.get("email") if callable(transport.get("email")) else None

    primary_status = "SKIPPED"
    fallback_channel = "NONE"
    fallback_status = "NOT_ATTEMPTED"
    delivery_status = "NOT_SENT"
    transport_errors = []
    sent_at = None

    if policy == "NOTIFY_NOW":
        rendered = render_notification_message(intent)
        # Defense-in-depth at the send boundary: value-redact any inline
        # credential pattern that could appear in rendered text (E2 already
        # redacts the intent; this guarantees no credential reaches Discord /
        # Email even for a malformed intent). Deterministic; semantic fields
        # are never modified -- only embedded secret VALUES in the message.
        if isinstance(rendered, dict):
            rendered = {
                k: (_e1_redact_sensitive_values(v) if isinstance(v, str) else v)
                for k, v in rendered.items()
            }
        if primary_channel == "DISCORD":
            if discord_fn is not None:
                ok, err = discord_fn(rendered["subject"], rendered["body"],
                                     rendered, discord_webhook_url)
            else:
                content = rendered["subject"] + "\n" + rendered["body"]
                ok, err = send_discord_message(content,
                                               webhook_url=discord_webhook_url)
            if ok:
                primary_status = "DELIVERED"
                delivery_status = "DELIVERED"
                fallback_status = "NOT_ATTEMPTED"
                sent_at = datetime.now().isoformat()
            else:
                primary_status = "FAILED"
                if err is not None:
                    transport_errors.append(
                        {"channel": "DISCORD", "error": err})
                # email fallback ONLY when policy allows
                if fallback_policy == "EMAIL_ON_PRIMARY_FAILURE":
                    fallback_channel = "EMAIL"
                    if email_fn is not None:
                        ok2, err2 = email_fn(rendered["subject"],
                                             rendered["body"], email_config)
                    else:
                        ok2, err2 = send_email_fallback(
                            rendered["subject"], rendered["body"],
                            email_config=email_config)
                    if ok2:
                        fallback_status = "DELIVERED"
                        delivery_status = "DELIVERED_VIA_FALLBACK"
                        sent_at = datetime.now().isoformat()
                    else:
                        fallback_status = "FAILED"
                        delivery_status = "FAILED"
                        if err2 is not None:
                            transport_errors.append(
                                {"channel": "EMAIL", "error": err2})
                else:
                    delivery_status = "FAILED"
        else:
            # NOTIFY_NOW but no usable primary channel in v0.1
            delivery_status = "FAILED"
            transport_errors.append({
                "channel": "NONE",
                "error": _e3_sanitize_transport_error("NO_PRIMARY_CHANNEL"),
            })
    else:
        # JOURNAL_ONLY / SUPPRESS -> NOT_SENT (never send)
        delivery_status = "NOT_SENT"

    result = {
        "schema_version": E3_DELIVERY_RESULT_SCHEMA_VERSION,
        "symbol": symbol,
        "attempted_at": attempted_at,
        "delivery_policy": policy,
        "notification_category": category,
        "severity": severity,
        "decision_state": decision,
        "primary_channel": primary_channel,
        "primary_status": primary_status,
        "fallback_channel": fallback_channel,
        "fallback_status": fallback_status,
        "delivery_status": delivery_status,
        "reason": reason,
        "fingerprint": fingerprint,
        "cycle_id": cycle_id,
        "transport_errors": transport_errors,
        "sent_at": sent_at,
        "semantic_snapshot": {
            "severity": severity,
            "decision_state": decision,
            "notification_category": category,
            "risk_flags": flags,
            "short_rationale": rationale,
        },
    }
    # E3.1 hotfix: value-level redaction of the delivery result. Fields that
    # may carry arbitrary user / model text (semantic_snapshot, reason) are
    # passed through the frozen shared helper so that even a raw intent which
    # bypassed E2 can never leak an inline credential into the Delivery Result
    # (Discord / Email bodies are already boundary-redacted). Only sensitive
    # VALUES are scrubbed; semantics (symbol/severity/decision/category/
    # policy/channels/fingerprint/cycle/status) are preserved. Input intent is
    # never mutated.
    result = _e1_redact_sensitive_values(result)
    return result




# ============================================================================
# E4 -- Decision Journal v0.1 (append-only audit/recording layer)
#
#   E4 is a RECORDING LAYER ONLY. It normalizes the outputs of Trigger / E1
#   Decision Envelope / Common AI Response + availability / E2 Notification
#   Intent / E3 Delivery Result into one append-only, auditable, searchable
#   JSONL journal. It makes NO market judgment and NEVER feeds back into
#   E1/E2/E3 (journal failure is non-authoritative: it can never change a
#   delivery decision or resend a notification).
#
#   Storage authority: DECISION_JOURNAL_PATH = <server_dir>/runtime/
#   decision_journal.jsonl  (a SEPARATE file from runtime_state.json; the only
#   writer is append_decision_journal_entry; E1/E2/E3 never touch it).
#
#   Security: E4 never stores account ids / webhook URLs / API keys / tokens /
#   secrets / SMTP credentials / raw market arrays. Every entry goes through
#   value-level sensitive redaction + raw-market stripping + strict JSON
#   validation inside the builder (defense in depth - never relies on upstream
#   having already cleaned). Entries are normalized field-by-field, NEVER a
#   whole-object dump of envelope / AI response / intent / delivery result.
#
#   Concurrency: single-process threading.Lock around append (duplicate scan +
#   write). Corrupt trailing / middle line => fail closed (no append, no
#   silent repair).
# ============================================================================

import threading

DECISION_JOURNAL_SCHEMA_VERSION = "decision_journal_v0.1"
DECISION_JOURNAL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "runtime",
    "decision_journal.jsonl",
)
_E4_JOURNAL_LOCK = threading.Lock()


def _e4_entry_id(cycle_id, fingerprint, symbol, event_type):
    """Deterministic / traceable entry id: sha256 over the logical event key
    (cycle_id + fingerprint + symbol + event_type). Same logical event always
    maps to the same entry_id (never random / timestamp-only)."""
    key = {
        "cycle_id": cycle_id,
        "fingerprint": fingerprint,
        "symbol": symbol,
        "event_type": event_type,
    }
    raw_key = json.dumps(key, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw_key).hexdigest()


def _e4_first_str(*values):
    for v in values:
        if isinstance(v, str):
            return v
    return None


def build_decision_journal_entry(journal_input):
    """Pure deterministic builder -> normalized Decision Journal Entry.

    Input keys (all optional; each is derived from its authoritative source
    when not explicitly provided):
      created_at            - clock/audit timestamp (only nondeterministic field)
      envelope              - E1 Decision Envelope dict
      ai_response           - validated Common AI Response dict (PRESENT only)
      ai_response_status    - PRESENT / NOT_REQUESTED / PENDING / FAILED
      intent                - E2 Notification Intent dict
      delivery_result       - E3 Delivery Result dict
      symbol / cycle_id / fingerprint / event_type / severity /
      previous_state / current_state / invocation_reason   (explicit overrides)
      source_versions       - optional dict overriding schema versions

    Pure: no network, no file write, no AI, no runtime write, no trade. The
    returned entry is canonical, sanitized (value redaction + raw-market
    stripping) and strict-JSON-safe.
    """
    if not isinstance(journal_input, dict):
        journal_input = {}
    envelope = journal_input.get("envelope")
    envelope = envelope if isinstance(envelope, dict) else {}
    ai_response = journal_input.get("ai_response")
    ai_response = ai_response if isinstance(ai_response, dict) else None
    intent = journal_input.get("intent")
    intent = intent if isinstance(intent, dict) else {}
    delivery = journal_input.get("delivery_result")
    delivery = delivery if isinstance(delivery, dict) else {}

    # ---- identity / traceability ----
    symbol = journal_input.get("symbol")
    if symbol is None:
        symbol = _e4_first_str(envelope.get("symbol"), intent.get("symbol"),
                               delivery.get("symbol"))
    assembly = envelope.get("assembly_context")
    assembly = assembly if isinstance(assembly, dict) else {}
    intent_src = intent.get("source")
    intent_src = intent_src if isinstance(intent_src, dict) else {}
    cycle_id = journal_input.get("cycle_id")
    if cycle_id is None:
        cycle_id = _e4_first_str(assembly.get("cycle_id"),
                                 intent_src.get("cycle_id"),
                                 delivery.get("cycle_id"))
    dedup_ctx = intent.get("dedup_context")
    dedup_ctx = dedup_ctx if isinstance(dedup_ctx, dict) else {}
    fingerprint = journal_input.get("fingerprint")
    if fingerprint is None:
        fingerprint = _e4_first_str(dedup_ctx.get("fingerprint"),
                                    delivery.get("fingerprint"))

    # ---- event context ----
    trigger = envelope.get("analysis_trigger")
    trigger = trigger if isinstance(trigger, dict) else {}
    event_type = journal_input.get("event_type")
    if event_type is None:
        event_type = trigger.get("event_type")
    severity = journal_input.get("severity")
    if severity is None:
        severity = _e4_first_str(intent.get("severity"), trigger.get("severity"))
    previous_state = journal_input.get("previous_state")
    if previous_state is None:
        previous_state = trigger.get("previous_state")
    current_state = journal_input.get("current_state")
    if current_state is None:
        current_state = trigger.get("current_state")
    invocation_reason = journal_input.get("invocation_reason")
    if invocation_reason is None:
        invocation_reason = intent.get("invocation_reason")

    # ---- AI / decision context ----
    ai_mode = envelope.get("ai_mode")
    ai_status = journal_input.get("ai_response_status")
    if ai_status is None:
        ai_status = intent.get("ai_response_status")
    request_id = intent.get("request_id")
    # decision fields come from a validated PRESENT response, EXCEPT in
    # DATA_QUALITY_ONLY where the AI decision must stay null (journal keeps
    # full audit risk flags instead - E4 section 14).
    decision_state = None
    provider = None
    model = None
    confidence = None
    short_rationale = None
    if ai_mode != "DATA_QUALITY_ONLY" and ai_response is not None             and ai_status == "PRESENT":
        decision_state = ai_response.get("decision_state")
        provider = ai_response.get("provider")
        model = ai_response.get("model")
        confidence = ai_response.get("confidence")
        short_rationale = ai_response.get("short_rationale")
    # full audit risk flags (allowed in the journal audit layer after sanitize)
    audit_ctx = intent.get("audit_context")
    audit_ctx = audit_ctx if isinstance(audit_ctx, dict) else {}
    full_flags = audit_ctx.get("risk_flags_full")
    if not isinstance(full_flags, list):
        full_flags = envelope.get("risk_flags")
    if not isinstance(full_flags, list):
        full_flags = []
    env_risk = envelope.get("risk_flags")
    if ai_response is not None and isinstance(ai_response.get("risk_flags"), list):
        decision_flags = list(ai_response.get("risk_flags")) or list(env_risk or [])
    else:
        decision_flags = list(env_risk or [])

    # ---- notification context ----
    notification_category = intent.get("notification_category")
    delivery_policy = intent.get("delivery_policy")
    primary_channel = intent.get("primary_channel")
    fallback_policy = intent.get("fallback_policy")
    suppression_reason = dedup_ctx.get("suppression_reason")

    # ---- delivery context ----
    # transport errors are normalized field-by-field (channel + safe category /
    # status / generic message). Raw exception text / URLs / credentials from a
    # malformed upstream delivery result never reach the journal (E4 keeps only
    # the already-sanitized category/status tokens produced by E3, and reduces
    # any unexpected free text to a generic marker).
    raw_errors = delivery.get("transport_errors")
    raw_errors = raw_errors if isinstance(raw_errors, list) else []
    transport_errors = []
    for item in raw_errors:
        if not isinstance(item, dict):
            continue
        err = item.get("error")
        err = err if isinstance(err, dict) else {}
        message = err.get("message")
        if not isinstance(message, str) or message not in ("TRANSPORT_ERROR",
                                                           "TRANSPORT_EXCEPTION"):
            message = "TRANSPORT_ERROR"
        status_code = err.get("status_code")
        if not isinstance(status_code, int) or isinstance(status_code, bool):
            status_code = None
        category = err.get("category")
        if not isinstance(category, str):
            category = "TRANSPORT_ERROR"
        transport_errors.append({
            "channel": item.get("channel"),
            "error": {"category": category, "status_code": status_code,
                      "message": message},
        })

    # ---- source versions ----
    sv_over = journal_input.get("source_versions")
    sv_over = sv_over if isinstance(sv_over, dict) else {}
    source_versions = {
        "decision_envelope_schema": sv_over.get(
            "decision_envelope_schema", envelope.get("schema_version")),
        "ai_response_schema": sv_over.get(
            "ai_response_schema",
            ai_response.get("schema_version") if ai_response is not None else None),
        "notification_intent_schema": sv_over.get(
            "notification_intent_schema", intent.get("schema_version")),
        "delivery_result_schema": sv_over.get(
            "delivery_result_schema", delivery.get("schema_version")),
    }

    created_at = journal_input.get("created_at")
    if created_at is None:
        created_at = _e4_first_str(delivery.get("attempted_at"),
                                   intent.get("created_at"),
                                   envelope.get("generated_at"))

    entry = {
        "schema_version": DECISION_JOURNAL_SCHEMA_VERSION,
        "entry_id": None,  # filled after canonical key fields are final
        "created_at": created_at,
        "symbol": symbol,
        "cycle_id": cycle_id,
        "fingerprint": fingerprint,
        "event_context": {
            "event_type": event_type,
            "severity": severity,
            "previous_state": previous_state,
            "current_state": current_state,
            "invocation_reason": invocation_reason,
        },
        "decision_context": {
            "ai_mode": ai_mode,
            "ai_response_status": ai_status,
            "request_id": request_id,
            "provider": provider,
            "model": model,
            "decision_state": decision_state,
            "confidence": confidence,
            "short_rationale": short_rationale,
            "risk_flags": decision_flags,
            "audit_risk_flags": full_flags,
        },
        "notification_context": {
            "notification_category": notification_category,
            "delivery_policy": delivery_policy,
            "primary_channel": primary_channel,
            "fallback_policy": fallback_policy,
            "suppression_reason": suppression_reason,
        },
        "delivery_context": {
            "delivery_status": delivery.get("delivery_status"),
            "primary_status": delivery.get("primary_status"),
            "fallback_status": delivery.get("fallback_status"),
            "transport_errors": transport_errors,
            "attempted_at": delivery.get("attempted_at"),
            "sent_at": delivery.get("sent_at"),
        },
        "source_versions": source_versions,
        "security_context": {"sanitized": True},
    }
    entry_id = _e4_entry_id(cycle_id, fingerprint, symbol,
                            event_type if isinstance(event_type, str) else None)
    entry["entry_id"] = entry_id
    # defense-in-depth: value redaction + raw-market stripping + canonical
    entry = _e1_redact_sensitive_values(entry)
    entry = _e1_strip_raw_market(entry)
    entry = _e1_clean(entry)
    # strict JSON guard (NaN / Infinity must never reach the journal)
    json.dumps(entry, ensure_ascii=False, allow_nan=False)
    return entry


def _e4_scan_duplicate(entry_id, path):
    """Read-only duplicate scan. Returns (duplicate_bool, corrupted_bool)."""
    if not os.path.exists(path):
        return False, False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    return False, True
                if isinstance(record, dict) and record.get("entry_id") == entry_id:
                    return True, False
    except OSError:
        return False, False
    return False, False


def append_decision_journal_entry(entry, journal_path=None):
    """Append-only journal writer. Authoritative writer for the journal file.

    Returns {"status": "APPENDED"|"DUPLICATE"|"FAILED", ...}. NEVER rewrites,
    edits or deletes historical entries; a repeated logical entry (same
    entry_id) is detected and returned as DUPLICATE without adding a line.
    Single-process concurrency is guarded by a threading.Lock. A corrupt
    existing line fails closed (no silent repair / truncation).
    """
    path = journal_path if isinstance(journal_path, str) else DECISION_JOURNAL_PATH
    if not isinstance(entry, dict):
        return {"status": "FAILED", "reason": "INVALID_ENTRY",
                "entry_id": None, "path": path}
    try:
        json.dumps(entry, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return {"status": "FAILED", "reason": "NOT_STRICT_JSON",
                "entry_id": entry.get("entry_id"), "path": path}
    entry_id = entry.get("entry_id")
    with _E4_JOURNAL_LOCK:
        try:
            duplicate, corrupted = _e4_scan_duplicate(entry_id, path)
        except OSError:
            return {"status": "FAILED", "reason": "JOURNAL_WRITE_FAILED",
                    "entry_id": entry_id, "path": path}
        if corrupted:
            return {"status": "FAILED", "reason": "CORRUPTED_JOURNAL",
                    "entry_id": entry_id, "path": path}
        if duplicate:
            return {"status": "DUPLICATE", "entry_id": entry_id, "path": path}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            line = json.dumps(entry, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode("utf-8") + b"\n"
            with open(path, "ab") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            return {"status": "FAILED", "reason": "JOURNAL_WRITE_FAILED",
                    "entry_id": entry_id, "path": path}
    return {"status": "APPENDED", "entry_id": entry_id, "path": path}


def read_recent_journal_entries(limit=20, journal_path=None):
    """Read-only: return the most recent N entries (newest first)."""
    path = journal_path if isinstance(journal_path, str) else DECISION_JOURNAL_PATH
    if not isinstance(limit, int) or limit <= 0:
        limit = 20
    entries = []
    if not os.path.exists(path):
        return {"ok": True, "entries": []}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(record, dict):
                    entries.append(record)
    except OSError:
        return {"ok": False, "entries": [], "reason": "JOURNAL_READ_FAILED"}
    return {"ok": True, "entries": entries[-limit:][::-1]}


def find_journal_entries(symbol=None, cycle_id=None, fingerprint=None,
                         decision_state=None, delivery_status=None,
                         limit=50, journal_path=None):
    """Read-only simple search across the journal. Filters are AND-combined."""
    path = journal_path if isinstance(journal_path, str) else DECISION_JOURNAL_PATH
    if not isinstance(limit, int) or limit <= 0:
        limit = 50
    matches = []
    if not os.path.exists(path):
        return {"ok": True, "entries": []}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(record, dict):
                    continue
                if symbol is not None and record.get("symbol") != symbol:
                    continue
                if cycle_id is not None and record.get("cycle_id") != cycle_id:
                    continue
                if fingerprint is not None and record.get("fingerprint") != fingerprint:
                    continue
                if decision_state is not None:
                    dc = record.get("decision_context")
                    dc = dc if isinstance(dc, dict) else {}
                    if dc.get("decision_state") != decision_state:
                        continue
                if delivery_status is not None:
                    dctx = record.get("delivery_context")
                    dctx = dctx if isinstance(dctx, dict) else {}
                    if dctx.get("delivery_status") != delivery_status:
                        continue
                matches.append(record)
    except OSError:
        return {"ok": False, "entries": [], "reason": "JOURNAL_READ_FAILED"}
    return {"ok": True, "entries": matches[-limit:][::-1]}


if __name__ == "__main__":
    mcp.run()

"""Cloud-safe read-only Eastmoney observation lane for A-share research data.

This module deliberately stops before intraday timestamp/currentness promotion.
It proves that cloud runtime can retrieve and normalize provider rows for the
A-share daily/15m/60m research surfaces without relying on QMT or a local PC.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from time import perf_counter
from typing import Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
SCHEMA = "stock_razor_cn_eastmoney_observation_v1"
TIMEFRAME_KLT = {"15m": "15", "60m": "60", "1d": "101"}
DEFAULT_LIMITS = {"15m": 480, "60m": 240, "1d": 260}
FIELDS1 = "f1,f2,f3,f4,f5,f6"
FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"


class EastmoneyObservationError(RuntimeError):
    pass


def normalize_cn_symbol(value: object) -> str:
    raw = str(value or "").strip().upper()
    for suffix in (".SH", ".SZ", ".BJ"):
        if raw.endswith(suffix):
            raw = raw[:-3]
            break
    for prefix in ("SH", "SZ", "BJ"):
        if raw.startswith(prefix) and len(raw) == 8:
            raw = raw[2:]
            break
    if not (len(raw) == 6 and raw.isdigit()):
        raise ValueError(f"unsupported A-share symbol: {value}")
    return raw


def eastmoney_secid(symbol: object) -> str:
    code = normalize_cn_symbol(symbol)
    if code.startswith(("5", "6", "9")):
        return f"1.{code}"
    if code.startswith(("0", "1", "2", "3")):
        return f"0.{code}"
    if code.startswith(("4", "8")):
        return f"0.{code}"
    raise ValueError(f"unsupported A-share market prefix: {code}")


def _http_json(url: str, *, timeout_seconds: float = 8.0) -> Mapping[str, object]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://quote.eastmoney.com/",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except Exception as exc:
        raise EastmoneyObservationError(
            f"eastmoney request failed: {type(exc).__name__}"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EastmoneyObservationError("eastmoney returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise EastmoneyObservationError("eastmoney JSON root must be an object")
    return payload


def build_kline_url(
    symbol: object,
    timeframe: str,
    *,
    limit: int | None = None,
    adjustment: str = "0",
) -> str:
    code = normalize_cn_symbol(symbol)
    frame = str(timeframe).strip().lower()
    if frame not in TIMEFRAME_KLT:
        raise ValueError(f"unsupported Eastmoney timeframe: {timeframe}")
    requested_limit = int(limit or DEFAULT_LIMITS[frame])
    if not 1 <= requested_limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    if adjustment not in {"0", "1", "2"}:
        raise ValueError("adjustment must be 0, 1, or 2")
    params = {
        "secid": eastmoney_secid(code),
        "klt": TIMEFRAME_KLT[frame],
        "fqt": adjustment,
        "fields1": FIELDS1,
        "fields2": FIELDS2,
        "end": "20500101",
        "lmt": str(requested_limit),
    }
    return EASTMONEY_KLINE_URL + "?" + urlencode(params)


def _number(value: str, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise EastmoneyObservationError(f"invalid numeric {field}") from exc
    if not math.isfinite(parsed):
        raise EastmoneyObservationError(f"non-finite numeric {field}")
    return parsed


def parse_kline_rows(payload: Mapping[str, object]) -> tuple[dict, ...]:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise EastmoneyObservationError("eastmoney response missing data")
    raw_rows = data.get("klines")
    if not isinstance(raw_rows, list):
        raise EastmoneyObservationError("eastmoney response missing klines")
    rows: list[dict] = []
    previous_label: str | None = None
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, str):
            raise EastmoneyObservationError(f"kline row {index} is not a string")
        fields = raw.split(",")
        if len(fields) < 7:
            raise EastmoneyObservationError(f"kline row {index} has too few fields")
        label = fields[0].strip()
        if not label:
            raise EastmoneyObservationError(f"kline row {index} missing label")
        if previous_label is not None and label <= previous_label:
            raise EastmoneyObservationError("kline labels must be strictly increasing")
        previous_label = label
        open_ = _number(fields[1], field="open")
        close = _number(fields[2], field="close")
        high = _number(fields[3], field="high")
        low = _number(fields[4], field="low")
        volume = _number(fields[5], field="volume")
        amount = _number(fields[6], field="amount")
        flags: list[str] = []
        if min(open_, high, low, close) <= 0:
            flags.append("NON_POSITIVE_PRICE")
        if high < max(open_, close, low) or low > min(open_, close, high):
            flags.append("INVALID_OHLC")
        if volume < 0:
            flags.append("NEGATIVE_VOLUME")
        if amount < 0:
            flags.append("NEGATIVE_AMOUNT")
        rows.append(
            {
                "label": label,
                "open": open_,
                "close": close,
                "high": high,
                "low": low,
                "volume_raw": volume,
                "amount_raw": amount,
                "quality_flags": flags,
            }
        )
    return tuple(rows)


def observe_eastmoney_symbol(
    symbol: object,
    *,
    observed_at_utc: datetime | None = None,
    fetch_json: Callable[[str], Mapping[str, object]] = _http_json,
    limits: Mapping[str, int] | None = None,
) -> dict:
    code = normalize_cn_symbol(symbol)
    now = observed_at_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    frames: dict[str, dict] = {}
    for timeframe in ("1d", "60m", "15m"):
        started = perf_counter()
        url = build_kline_url(
            code,
            timeframe,
            limit=(limits or {}).get(timeframe),
            adjustment="0",
        )
        try:
            rows = parse_kline_rows(fetch_json(url))
            status = "PASS" if rows else "NO_DATA"
            error = None
        except Exception as exc:
            rows = ()
            status = "BLOCKED"
            error = type(exc).__name__
        frames[timeframe] = {
            "status": status,
            "error": error,
            "row_count": len(rows),
            "rows": list(rows),
            "request_latency_ms": round((perf_counter() - started) * 1000, 3),
            "timestamp_semantic": "DAILY_DATE" if timeframe == "1d" else "UNKNOWN",
            "currentness": "UNPROVEN",
            "adjustment": "NONE",
        }
    passed = sum(item["status"] == "PASS" for item in frames.values())
    overall = "PASS" if passed == len(frames) else ("PARTIAL" if passed else "BLOCKED")
    return {
        "symbol": code,
        "secid": eastmoney_secid(code),
        "status": overall,
        "provider": "eastmoney",
        "upstream_lineage_id": "eastmoney",
        "endpoint": EASTMONEY_KLINE_URL,
        "observed_at_utc": now.astimezone(timezone.utc).isoformat(),
        "timeframes": frames,
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def build_cn_cloud_observation(
    symbols: Iterable[object],
    *,
    repo_sha: str,
    runtime_instance_id: str,
    sequence: int,
    observed_at_utc: datetime | None = None,
    fetch_json: Callable[[str], Mapping[str, object]] = _http_json,
) -> dict:
    normalized = tuple(
        dict.fromkeys(normalize_cn_symbol(symbol) for symbol in symbols)
    )
    if not normalized:
        raise ValueError("at least one A-share symbol is required")
    sha = str(repo_sha).strip().lower()
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ValueError("repo_sha must be an exact 40-character git SHA")
    if not str(runtime_instance_id).strip():
        raise ValueError("runtime_instance_id is required")
    if int(sequence) <= 0:
        raise ValueError("sequence must be positive")
    now = observed_at_utc or datetime.now(timezone.utc)
    results = {
        symbol: observe_eastmoney_symbol(
            symbol,
            observed_at_utc=now,
            fetch_json=fetch_json,
        )
        for symbol in normalized
    }
    passed = sum(item["status"] == "PASS" for item in results.values())
    status = "PASS" if passed == len(results) else ("PARTIAL" if passed else "BLOCKED")
    return {
        "schema": SCHEMA,
        "repo_sha": sha,
        "runtime_instance_id": str(runtime_instance_id).strip(),
        "sequence": int(sequence),
        "emitted_at_utc": now.astimezone(timezone.utc).isoformat(),
        "status": status,
        "symbols": results,
        "provider": "eastmoney",
        "provider_lineage": "eastmoney",
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }

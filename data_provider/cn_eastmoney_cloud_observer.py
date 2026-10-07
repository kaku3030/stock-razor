"""Cloud-safe read-only A-share observation lane.

Eastmoney is the primary cloud source. Tencent is an independent-lineage
fallback for daily/15m/60m K-lines. This layer deliberately stops before
intraday timestamp/currentness promotion and never authorizes trading.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from time import perf_counter, sleep
from typing import Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


EASTMONEY_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
TENCENT_MINUTE_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"
TENCENT_DAILY_URL = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline"
SCHEMA = "stock_razor_cn_eastmoney_observation_v1"
TIMEFRAME_KLT = {"15m": "15", "60m": "60", "1d": "101"}
DEFAULT_LIMITS = {"15m": 480, "60m": 240, "1d": 260}
FIELDS1 = "f1,f2,f3,f4,f5,f6"
FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"


class CloudObservationError(RuntimeError):
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
    if code.startswith(("0", "1", "2", "3", "4", "8")):
        return f"0.{code}"
    raise ValueError(f"unsupported A-share market prefix: {code}")


def tencent_symbol(symbol: object) -> str:
    code = normalize_cn_symbol(symbol)
    if code.startswith(("5", "6", "9")):
        return f"sh{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sz{code}"


def _http_json(
    url: str,
    *,
    timeout_seconds: float = 8.0,
    max_attempts: int = 3,
    sleep_fn: Callable[[float], None] = sleep,
) -> Mapping[str, object]:
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    referer = (
        "https://gu.qq.com/"
        if "gtimg.cn" in url
        else "https://quote.eastmoney.com/"
    )
    raw: bytes | None = None
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
                "Referer": referer,
                "Connection": "close",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
            break
        except Exception as exc:
            last_exc = exc
            if attempt + 1 < max_attempts:
                sleep_fn(0.5 * (2**attempt))
    if raw is None:
        assert last_exc is not None
        raise CloudObservationError(
            f"provider request failed after {max_attempts} attempts: {type(last_exc).__name__}"
        ) from last_exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CloudObservationError("provider returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise CloudObservationError("provider JSON root must be an object")
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


def build_tencent_kline_url(
    symbol: object,
    timeframe: str,
    *,
    limit: int | None = None,
) -> str:
    frame = str(timeframe).strip().lower()
    if frame not in TIMEFRAME_KLT:
        raise ValueError(f"unsupported Tencent timeframe: {timeframe}")
    requested_limit = int(limit or DEFAULT_LIMITS[frame])
    if not 1 <= requested_limit <= 5000:
        raise ValueError("limit must be between 1 and 5000")
    code = tencent_symbol(symbol)
    if frame == "1d":
        value = f"{code},day,,,{requested_limit}"
        return TENCENT_DAILY_URL + "?" + urlencode({"param": value})
    minutes = frame[:-1]
    value = f"{code},m{minutes},,{requested_limit}"
    return TENCENT_MINUTE_URL + "?" + urlencode({"param": value})


def _number(value: object, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CloudObservationError(f"invalid numeric {field}") from exc
    if not math.isfinite(parsed):
        raise CloudObservationError(f"non-finite numeric {field}")
    return parsed


def _quality_flags(
    open_: float,
    close: float,
    high: float,
    low: float,
    volume: float,
    amount: float | None,
) -> list[str]:
    flags: list[str] = []
    if min(open_, high, low, close) <= 0:
        flags.append("NON_POSITIVE_PRICE")
    if high < max(open_, close, low) or low > min(open_, close, high):
        flags.append("INVALID_OHLC")
    if volume < 0:
        flags.append("NEGATIVE_VOLUME")
    if amount is not None and amount < 0:
        flags.append("NEGATIVE_AMOUNT")
    return flags


def parse_kline_rows(payload: Mapping[str, object]) -> tuple[dict, ...]:
    """Parse Eastmoney rows while preserving unverified provider units."""

    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise CloudObservationError("eastmoney response missing data")
    raw_rows = data.get("klines")
    if not isinstance(raw_rows, list):
        raise CloudObservationError("eastmoney response missing klines")
    rows: list[dict] = []
    previous_label: str | None = None
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, str):
            raise CloudObservationError(f"kline row {index} is not a string")
        fields = raw.split(",")
        if len(fields) < 7:
            raise CloudObservationError(f"kline row {index} has too few fields")
        label = fields[0].strip()
        if not label:
            raise CloudObservationError(f"kline row {index} missing label")
        if previous_label is not None and label <= previous_label:
            raise CloudObservationError("kline labels must be strictly increasing")
        previous_label = label
        open_ = _number(fields[1], field="open")
        close = _number(fields[2], field="close")
        high = _number(fields[3], field="high")
        low = _number(fields[4], field="low")
        volume = _number(fields[5], field="volume")
        amount = _number(fields[6], field="amount")
        rows.append(
            {
                "label": label,
                "provider_label_raw": label,
                "open": open_,
                "close": close,
                "high": high,
                "low": low,
                "volume_raw": volume,
                "volume_unit": "PROVIDER_RAW_UNVERIFIED",
                "amount_raw": amount,
                "amount_unit": "PROVIDER_RAW_UNVERIFIED",
                "provider": "eastmoney",
                "quality_flags": _quality_flags(
                    open_, close, high, low, volume, amount
                ),
            }
        )
    return tuple(rows)


def _normalize_tencent_label(value: object, timeframe: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if timeframe == "1d":
        if len(raw) == 8 and raw.isdigit():
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}", raw
        return raw, raw
    if len(raw) == 12 and raw.isdigit():
        return (
            f"{raw[:4]}-{raw[4:6]}-{raw[6:8]} {raw[8:10]}:{raw[10:12]}",
            raw,
        )
    return raw, raw


def parse_tencent_kline_rows(
    payload: Mapping[str, object],
    *,
    symbol: object,
    timeframe: str,
) -> tuple[dict, ...]:
    frame = str(timeframe).strip().lower()
    api_symbol = tencent_symbol(symbol)
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise CloudObservationError("tencent response missing data")
    item = data.get(api_symbol)
    if not isinstance(item, Mapping):
        raise CloudObservationError("tencent response missing symbol")
    key = "day" if frame == "1d" else f"m{frame[:-1]}"
    raw_rows = item.get(key)
    if not isinstance(raw_rows, list):
        raise CloudObservationError("tencent response missing klines")
    rows: list[dict] = []
    previous_label: str | None = None
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, list) or len(raw) < 6:
            raise CloudObservationError(f"tencent row {index} has invalid shape")
        label, raw_label = _normalize_tencent_label(raw[0], frame)
        if not label:
            raise CloudObservationError(f"tencent row {index} missing label")
        if previous_label is not None and label <= previous_label:
            raise CloudObservationError("tencent labels must be strictly increasing")
        previous_label = label
        open_ = _number(raw[1], field="open")
        close = _number(raw[2], field="close")
        high = _number(raw[3], field="high")
        low = _number(raw[4], field="low")
        volume = _number(raw[5], field="volume")
        rows.append(
            {
                "label": label,
                "provider_label_raw": raw_label,
                "open": open_,
                "close": close,
                "high": high,
                "low": low,
                "volume_raw": volume,
                "volume_unit": "HAND",
                "amount_raw": None,
                "amount_unit": "UNAVAILABLE",
                "provider": "tencent",
                "quality_flags": _quality_flags(
                    open_, close, high, low, volume, None
                ),
            }
        )
    return tuple(rows)


def _frame_observation(
    code: str,
    timeframe: str,
    *,
    eastmoney_fetch_json: Callable[[str], Mapping[str, object]],
    tencent_fetch_json: Callable[[str], Mapping[str, object]],
    limit: int | None,
) -> dict:
    started = perf_counter()
    primary_error: str | None = None
    try:
        rows = parse_kline_rows(
            eastmoney_fetch_json(
                build_kline_url(code, timeframe, limit=limit, adjustment="0")
            )
        )
        if not rows:
            raise CloudObservationError("eastmoney returned no rows")
        provider_used = "eastmoney"
        provider_lineage = "eastmoney"
        fallback_from = None
        fallback_reason = None
    except Exception as exc:
        primary_error = type(exc).__name__
        try:
            rows = parse_tencent_kline_rows(
                tencent_fetch_json(
                    build_tencent_kline_url(code, timeframe, limit=limit)
                ),
                symbol=code,
                timeframe=timeframe,
            )
            if not rows:
                raise CloudObservationError("tencent returned no rows")
            provider_used = "tencent"
            provider_lineage = "tencent"
            fallback_from = "eastmoney"
            fallback_reason = primary_error
        except Exception as fallback_exc:
            rows = ()
            provider_used = None
            provider_lineage = None
            fallback_from = "eastmoney"
            fallback_reason = (
                f"{primary_error}|TENCENT:{type(fallback_exc).__name__}"
            )
    status = "PASS" if rows else "BLOCKED"
    return {
        "status": status,
        "error": None if rows else fallback_reason,
        "row_count": len(rows),
        "rows": list(rows),
        "request_latency_ms": round((perf_counter() - started) * 1000, 3),
        "provider_used": provider_used,
        "provider_lineage": provider_lineage,
        "fallback_from": fallback_from,
        "fallback_reason": fallback_reason,
        "timestamp_semantic": "DAILY_DATE" if timeframe == "1d" else "UNKNOWN",
        "currentness": "UNPROVEN",
        "adjustment": "NONE",
    }


def observe_cn_cloud_symbol(
    symbol: object,
    *,
    observed_at_utc: datetime | None = None,
    eastmoney_fetch_json: Callable[[str], Mapping[str, object]] = _http_json,
    tencent_fetch_json: Callable[[str], Mapping[str, object]] = _http_json,
    limits: Mapping[str, int] | None = None,
) -> dict:
    code = normalize_cn_symbol(symbol)
    now = observed_at_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone-aware")
    frames = {
        timeframe: _frame_observation(
            code,
            timeframe,
            eastmoney_fetch_json=eastmoney_fetch_json,
            tencent_fetch_json=tencent_fetch_json,
            limit=(limits or {}).get(timeframe),
        )
        for timeframe in ("1d", "60m", "15m")
    }
    passed = sum(item["status"] == "PASS" for item in frames.values())
    overall = "PASS" if passed == len(frames) else ("PARTIAL" if passed else "BLOCKED")
    providers_used = sorted(
        {
            item["provider_used"]
            for item in frames.values()
            if item["provider_used"]
        }
    )
    return {
        "symbol": code,
        "secid": eastmoney_secid(code),
        "status": overall,
        "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
        "providers_used": providers_used,
        "observed_at_utc": now.astimezone(timezone.utc).isoformat(),
        "timeframes": frames,
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def observe_eastmoney_symbol(*args, **kwargs) -> dict:
    """Backward-compatible alias for the now governed multi-source observer."""

    return observe_cn_cloud_symbol(*args, **kwargs)


def build_cn_cloud_observation(
    symbols: Iterable[object],
    *,
    repo_sha: str,
    runtime_instance_id: str,
    sequence: int,
    observed_at_utc: datetime | None = None,
    eastmoney_fetch_json: Callable[[str], Mapping[str, object]] = _http_json,
    tencent_fetch_json: Callable[[str], Mapping[str, object]] = _http_json,
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
        symbol: observe_cn_cloud_symbol(
            symbol,
            observed_at_utc=now,
            eastmoney_fetch_json=eastmoney_fetch_json,
            tencent_fetch_json=tencent_fetch_json,
        )
        for symbol in normalized
    }
    passed = sum(item["status"] == "PASS" for item in results.values())
    status = "PASS" if passed == len(results) else ("PARTIAL" if passed else "BLOCKED")
    providers_used = sorted(
        {
            provider
            for item in results.values()
            for provider in item["providers_used"]
        }
    )
    return {
        "schema": SCHEMA,
        "repo_sha": sha,
        "runtime_instance_id": str(runtime_instance_id).strip(),
        "sequence": int(sequence),
        "emitted_at_utc": now.astimezone(timezone.utc).isoformat(),
        "status": status,
        "symbols": results,
        "provider_policy": "EASTMONEY_PRIMARY_TENCENT_FALLBACK",
        "providers_used": providers_used,
        "provider_lineages": ["eastmoney", "tencent"],
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }

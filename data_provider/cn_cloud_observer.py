"""Multi-source cloud A-share observation lane.

Primary research surfaces:
- Tencent direct daily K-line
- Sina 15m / 60m K-line

Eastmoney remains an optional same-market observation/cross-check source but is
not allowed to become a single point of failure for cloud data availability.
No source in this module can promote intraday timestamp semantics, currentness,
Radar admission, or execution authorization.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from time import perf_counter
from typing import Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .cn_eastmoney_cloud_observer import observe_eastmoney_symbol


SCHEMA = "stock_razor_cn_cloud_observation_v1"
SINA_URL = (
    "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
    "CN_MarketData.getKLineData"
)
TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


class CNCloudObservationError(RuntimeError):
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


def _market_prefix(code: str) -> str:
    return "sh" if code.startswith(("5", "6", "9")) else "sz"


def _http_json(url: str, *, timeout_seconds: float = 8.0) -> object:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://finance.qq.com/",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except Exception as exc:
        raise CNCloudObservationError(
            f"provider request failed: {type(exc).__name__}"
        ) from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CNCloudObservationError("provider returned invalid JSON") from exc


def _num(value: object, *, field: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise CNCloudObservationError(f"invalid numeric {field}") from exc
    if not math.isfinite(parsed):
        raise CNCloudObservationError(f"non-finite numeric {field}")
    return parsed


def _validated_row(
    label: object,
    open_: object,
    close: object,
    high: object,
    low: object,
    volume: object,
    amount: object | None = None,
) -> dict:
    label_text = str(label or "").strip()
    if not label_text:
        raise CNCloudObservationError("row missing label")
    o = _num(open_, field="open")
    c = _num(close, field="close")
    h = _num(high, field="high")
    l = _num(low, field="low")
    v = _num(volume, field="volume")
    a = None if amount in (None, "") else _num(amount, field="amount")
    flags: list[str] = []
    if min(o, h, l, c) <= 0:
        flags.append("NON_POSITIVE_PRICE")
    if h < max(o, c, l) or l > min(o, c, h):
        flags.append("INVALID_OHLC")
    if v < 0:
        flags.append("NEGATIVE_VOLUME")
    if a is not None and a < 0:
        flags.append("NEGATIVE_AMOUNT")
    return {
        "label": label_text,
        "open": o,
        "close": c,
        "high": h,
        "low": l,
        "volume_raw": v,
        "amount_raw": a,
        "quality_flags": flags,
    }


def fetch_tencent_daily(
    symbol: object,
    *,
    count: int = 260,
    fetch_json: Callable[[str], object] = _http_json,
) -> tuple[dict, ...]:
    code = normalize_cn_symbol(symbol)
    tencent_symbol = _market_prefix(code) + code
    params = {
        "param": f"{tencent_symbol},day,,,{int(count)},qfq",
    }
    payload = fetch_json(TENCENT_URL + "?" + urlencode(params))
    if not isinstance(payload, Mapping):
        raise CNCloudObservationError("Tencent root must be an object")
    data = payload.get("data")
    item = data.get(tencent_symbol) if isinstance(data, Mapping) else None
    if not isinstance(item, Mapping):
        raise CNCloudObservationError("Tencent response missing symbol")
    raw_rows = item.get("qfqday") or item.get("day") or []
    if not isinstance(raw_rows, list):
        raise CNCloudObservationError("Tencent response missing daily rows")
    rows: list[dict] = []
    last_label: str | None = None
    for raw in raw_rows:
        if not isinstance(raw, list) or len(raw) < 6:
            continue
        row = _validated_row(
            raw[0], raw[1], raw[2], raw[3], raw[4], raw[5],
            raw[6] if len(raw) > 6 else None,
        )
        if last_label is not None and row["label"] <= last_label:
            raise CNCloudObservationError("Tencent labels not strictly increasing")
        last_label = row["label"]
        rows.append(row)
    return tuple(rows)


def fetch_sina_intraday(
    symbol: object,
    timeframe: str,
    *,
    count: int = 240,
    fetch_json: Callable[[str], object] = _http_json,
) -> tuple[dict, ...]:
    code = normalize_cn_symbol(symbol)
    frame = str(timeframe).strip().lower()
    if frame not in {"15m", "60m"}:
        raise ValueError("Sina intraday timeframe must be 15m or 60m")
    params = {
        "symbol": _market_prefix(code) + code,
        "scale": "15" if frame == "15m" else "60",
        "ma": "5",
        "datalen": str(int(count)),
    }
    payload = fetch_json(SINA_URL + "?" + urlencode(params))
    if not isinstance(payload, list):
        raise CNCloudObservationError("Sina response must be a list")
    rows: list[dict] = []
    last_label: str | None = None
    for raw in payload:
        if not isinstance(raw, Mapping):
            continue
        row = _validated_row(
            raw.get("day"),
            raw.get("open"),
            raw.get("close"),
            raw.get("high"),
            raw.get("low"),
            raw.get("volume"),
            raw.get("amount"),
        )
        if last_label is not None and row["label"] <= last_label:
            raise CNCloudObservationError("Sina labels not strictly increasing")
        last_label = row["label"]
        rows.append(row)
    return tuple(rows)


def _frame_result(
    provider: str,
    rows: tuple[dict, ...],
    started_at: float,
    *,
    timestamp_semantic: str,
) -> dict:
    return {
        "status": "PASS" if rows else "NO_DATA",
        "provider": provider,
        "provider_lineage": provider,
        "row_count": len(rows),
        "rows": list(rows),
        "request_latency_ms": round((perf_counter() - started_at) * 1000, 3),
        "timestamp_semantic": timestamp_semantic,
        "currentness": "UNPROVEN",
    }


def observe_cn_symbol(
    symbol: object,
    *,
    observed_at_utc: datetime | None = None,
    fetch_json: Callable[[str], object] = _http_json,
    include_eastmoney_crosscheck: bool = True,
) -> dict:
    code = normalize_cn_symbol(symbol)
    now = observed_at_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("observed_at_utc must be timezone-aware")

    frames: dict[str, dict] = {}
    for timeframe in ("1d", "60m", "15m"):
        started = perf_counter()
        try:
            rows = (
                fetch_tencent_daily(code, fetch_json=fetch_json)
                if timeframe == "1d"
                else fetch_sina_intraday(code, timeframe, fetch_json=fetch_json)
            )
            frames[timeframe] = _frame_result(
                "tencent" if timeframe == "1d" else "sina",
                rows,
                started,
                timestamp_semantic="DAILY_DATE" if timeframe == "1d" else "UNKNOWN",
            )
        except Exception as exc:
            frames[timeframe] = {
                "status": "BLOCKED",
                "provider": "tencent" if timeframe == "1d" else "sina",
                "provider_lineage": "tencent" if timeframe == "1d" else "sina",
                "error": type(exc).__name__,
                "row_count": 0,
                "rows": [],
                "request_latency_ms": round((perf_counter() - started) * 1000, 3),
                "timestamp_semantic": "DAILY_DATE" if timeframe == "1d" else "UNKNOWN",
                "currentness": "UNPROVEN",
            }

    eastmoney: dict | None = None
    if include_eastmoney_crosscheck:
        try:
            eastmoney = observe_eastmoney_symbol(code, observed_at_utc=now)
        except Exception as exc:
            eastmoney = {
                "status": "BLOCKED",
                "provider": "eastmoney",
                "upstream_lineage_id": "eastmoney",
                "error": type(exc).__name__,
                "research_only": True,
                "radar_admission": "BLOCKED",
                "live_trade": False,
            }

    passed = sum(item["status"] == "PASS" for item in frames.values())
    overall = "PASS" if passed == 3 else ("PARTIAL" if passed else "BLOCKED")
    return {
        "symbol": code,
        "status": overall,
        "primary_timeframes": frames,
        "optional_crosscheck": {"eastmoney": eastmoney} if eastmoney is not None else {},
        "independent_primary_lineages": ["tencent", "sina"],
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
    fetch_json: Callable[[str], object] = _http_json,
    include_eastmoney_crosscheck: bool = True,
) -> dict:
    normalized = tuple(dict.fromkeys(normalize_cn_symbol(s) for s in symbols))
    if not normalized:
        raise ValueError("at least one A-share symbol is required")
    sha = str(repo_sha).strip().lower()
    if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
        raise ValueError("repo_sha must be exact 40-character git SHA")
    if not str(runtime_instance_id).strip():
        raise ValueError("runtime_instance_id is required")
    if int(sequence) <= 0:
        raise ValueError("sequence must be positive")
    now = observed_at_utc or datetime.now(timezone.utc)
    results = {
        symbol: observe_cn_symbol(
            symbol,
            observed_at_utc=now,
            fetch_json=fetch_json,
            include_eastmoney_crosscheck=include_eastmoney_crosscheck,
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
        "primary_lineages": ["tencent", "sina"],
        "optional_crosscheck_lineages": ["eastmoney"],
        "intraday_timestamp_semantics_proven": False,
        "intraday_currentness_proven": False,
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }

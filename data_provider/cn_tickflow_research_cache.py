"""Read-only, isolated TickFlow Premium minute observation (not canonical/trade)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from math import isfinite
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import os
import re
import tempfile
from typing import Any

CN = ZoneInfo("Asia/Shanghai")
SCHEMA = "stock_razor_cn_tickflow_research_observation_v0_1"
DEFAULT_PATH = "/run/stock-razor-cn-tickflow/latest-research-observation.json"
SYMBOLS = ("159611.SZ", "159209.SZ", "512730.SH", "159363.SZ")
# Expert capacity ceiling. The deployment default remains 20; explicit scans
# may use the full 200 only through the bounded batch path.
MAX_SCAN_SYMBOLS = 200
TIMEFRAMES = ("1m", "5m", "15m", "60m", "1d")
# Twenty symbols × five periods requires a larger bounded private envelope;
# this remains a hard reader/writer limit and is not public market-data output.
MAX_BYTES = 64_000_000
MAX_AGE_SECONDS = 180
_LABEL_END = {
    "1m": frozenset(
        f"{minute//60:02d}:{minute%60:02d}"
        for minute in (*range(9*60+31, 11*60+31),
                       *range(13*60+1, 15*60+1))
    ),
    "15m": frozenset(("09:45","10:00","10:15","10:30","10:45","11:00",
       "11:15","11:30","13:15","13:30","13:45","14:00","14:15",
       "14:30","14:45","15:00")),
    "60m": frozenset(("10:30","11:30","14:00","15:00")),
    "5m": frozenset(f"{minute//60:02d}:{minute%60:02d}"
        for minute in (*range(9*60+35,11*60+31,5),
                       *range(13*60+5,15*60+1,5))),
    # The provider 1d row is calendar-date stamped 00:00 local;
    # not an exchange bar-end timestamp and never proof of close.
    "1d": frozenset(("00:00",)),
}
_SYMBOL_RE = re.compile(r"^(?:[0-9]{6})\.(?:SH|SZ)$")
_ALLOWED_PERIODS = {"1m":240,"5m":144,"15m":96,"60m":24,"1d":40}
# Recover at most four omitted entries per period and twenty per full scan.
_MAX_BATCH_FALLBACKS_PER_PERIOD = 4
_MAX_BATCH_FALLBACKS_PER_OBSERVATION = (
    _MAX_BATCH_FALLBACKS_PER_PERIOD * len(_ALLOWED_PERIODS)
)
_SOURCE = "TICKFLOW_PREMIUM"


class _BatchSymbolFallbackError(RuntimeError):
    """Provider-free public failure for a missing-symbol recovery attempt."""


def resolve_scan_symbols(value: str | None = None) -> tuple[str, ...]:
    """Resolve an explicit, bounded scan list without changing the safe default."""
    if value is None or not value.strip():
        return SYMBOLS
    symbols = tuple(item.strip().upper() for item in value.replace(";", ",").split(",")
                    if item.strip())
    if (not symbols or len(symbols) > MAX_SCAN_SYMBOLS
            or len(set(symbols)) != len(symbols)
            or not all(_SYMBOL_RE.fullmatch(item) for item in symbols)):
        raise ValueError("invalid scan symbols")
    return symbols


class _BatchKlinesFacade:
    """Materialize bounded provider batches for each timeframe's symbol subset."""

    def __init__(self, client: Any, period_symbols: dict[str, tuple[str, ...]],
                 periods: dict[str, int], batch_size: int) -> None:
        self._frames: dict[tuple[str, str], Any] = {}
        self._fallback_count = 0
        for period, period_symbol_list in period_symbols.items():
            count = periods[period]
            try:
                method = (client.klines.batch if period == "1d"
                          else client.klines.intraday_batch)
                kwargs = {
                    "period": period, "count": count, "as_dataframe": False,
                    "show_progress": False, "max_workers": 5,
                    "batch_size": batch_size,
                }
                if period == "1d":
                    kwargs["adjust"] = "none"
                result = method(list(period_symbol_list), **kwargs)
                if not isinstance(result, dict):
                    raise ValueError("batch SDK shape invalid")
                missing = tuple(symbol for symbol in period_symbol_list if symbol not in result)
                if (len(missing) > _MAX_BATCH_FALLBACKS_PER_PERIOD
                        or self._fallback_count + len(missing)
                        > _MAX_BATCH_FALLBACKS_PER_OBSERVATION):
                    raise ValueError("batch SDK symbol missing")
                # Count attempted calls, including a later provider failure.
                self._fallback_count += len(missing)
                for symbol in period_symbol_list:
                    if symbol in result:
                        frame = result[symbol]
                    else:
                        # Recover only a small number of omitted batch entries.
                        # Larger gaps fail closed to cap provider calls and cost.
                        try:
                            if period == "1d":
                                frame = client.klines.get(
                                    symbol, period=period, count=count,
                                    as_dataframe=False, adjust="none",
                                )
                            else:
                                frame = client.klines.intraday(
                                    symbol, period=period, count=count,
                                    as_dataframe=False,
                                )
                        except Exception:
                            failure = _BatchSymbolFallbackError(
                                "batch symbol fallback failed"
                            )
                            failure._tickflow_stage = (
                                f"BATCH_{period.upper()}_SYMBOL_FALLBACK"
                            )
                            raise failure from None
                    self._frames[(symbol, period)] = frame
            except Exception as exc:
                # Batch errors occur before the per-symbol normalization loop.
                # Preserve a finite local stage without exposing provider text.
                if not isinstance(exc, _BatchSymbolFallbackError):
                    exc._tickflow_stage = f"BATCH_{period.upper()}_FETCH"
                raise

    def get(self, symbol: str, *, period: str, count: int,
            adjust: str, as_dataframe: bool) -> Any:
        del count, adjust, as_dataframe
        return self._frames[(symbol, period)]

def _timestamp(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError("invalid provider timestamp")
    epoch = float(value)
    if epoch > 1e12:
        epoch /= 1000
    if not 1_500_000_000 <= epoch <= 2_400_000_000:
        raise ValueError("provider epoch outside bounded range")
    return datetime.fromtimestamp(epoch, timezone.utc)

def _number(row: dict, *names: str) -> float:
    for key in names:
        if key in row:
            value = row[key]
            if isinstance(value, bool) or not isinstance(value,(int,float)) or not isfinite(value):
                raise ValueError("invalid provider number")
            return float(value)
    raise ValueError("missing provider column")


def _vendor_ohlc_float_gap_bucket(op: float, hi: float, lo: float, cl: float) -> str:
    """Classify rejected OHLC without exporting prices or changing any bars.

    TickFlow support's <=1e-5 suggestion is research diagnostics only.
    Absolute CNY error is NOT the same as ETF tick size or bps.
    """
    try:
        o,h,l,c=(Decimal(str(x)) for x in (op,hi,lo,cl))
        if not all(x.is_finite() and x>0 for x in (o,h,l,c)):
            return "UNKNOWN"
        excess=max(Decimal("0"),max(o,c,l)-h,l-min(o,c,h))
        return ("WITHIN_1E_MINUS_5" if excess<=Decimal("0.00001")
                else "OVER_1E_MINUS_5")
    except (InvalidOperation,TypeError,ValueError,OverflowError):
        return "UNKNOWN"


def _vendor_etf_tick_lattice_shape_valid(op: float, hi: float, lo: float, cl: float) -> bool:
    """Only tiny serialized ETF float drift; no rounding/mutation of OHLC.

    Post-close *historical research* may preserve original <=1e-5 drift
    only when every field is already within <=1e-5 of a 0.001 CNY tick
    and the rounded lattice would enclose the candle's body.
    """
    try:
        prices = tuple(Decimal(str(x)) for x in (op, hi, lo, cl))
        if not all(x.is_finite() and x > 0 for x in prices):
            return False
        tick = Decimal("0.001")
        lattice = tuple(x.quantize(tick, rounding=ROUND_HALF_UP) for x in prices)
        if not all(abs(raw - snapped) <= Decimal("0.00001")
                   for raw, snapped in zip(prices, lattice)):
            return False
        o, h, l, c = lattice
        return h >= max(o, c, l) and l <= min(o, c, h)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return False


def _post_close_research_eligible(stamp: datetime, now_utc: datetime) -> bool:
    """Only settled-clock post-close historical research (never live/current)."""
    local = now_utc.astimezone(CN)
    return (
        stamp.astimezone(CN).date() == local.date()
        and (local.hour, local.minute) >= (15, 2)
        and stamp <= now_utc - timedelta(seconds=90)
    )


def _select_timestamp(row: dict) -> datetime:
    for key in ("timestamp", "time", "datetime", "date"):
        if key in row:
            return _timestamp(row[key])
    raise ValueError("no provider timestamp")

def normalize_bars(frame: Any, timeframe: str, *, now_utc: datetime,
                   quarantine_counts: dict[str,int]|None=None,
                   quarantine_evidence: dict[str,int]|None=None) -> list[dict]:
    """Price-bearing bars stay on AWS; no current-bar finality is asserted.

    Optional fixed-enum quarantine counters preserve *why* current-day rows
    were withheld without logging price, raw provider payload or timestamps.
    """
    def quarantine(reason: str) -> None:
        if quarantine_counts is not None:
            quarantine_counts[reason]=quarantine_counts.get(reason,0)+1
    def summarize_invalid_ohlc(op: float, hi: float, lo: float, cl: float,
                               reason: str) -> None:
        # This is PRIVATE AWS accounting, strictly restricted to rejected
        # TODAY rows. Prices/timestamps must never leave the collector.
        if quarantine_evidence is None or reason not in (
                "invalid OHLCVA high below body",
                "invalid OHLCVA low above body"):
            return
        gap=max(0.0, max(op,cl,lo)-hi,lo-min(op,cl,hi))
        bps=(gap/max(op,cl))*10000
        category=("GAP_LT_1BP" if bps<1 else
                  "GAP_1_TO_10BP" if bps<10 else
                  "GAP_10_TO_100BP" if bps<100 else
                  "GAP_GE_100BP")
        quarantine_evidence[category]=quarantine_evidence.get(category,0)+1
        if lo >= max(op,cl) and hi <= min(op,cl) and hi<lo:
            key="HILO_SWAP_WOULD_ENCLOSE_BODY"
            quarantine_evidence[key]=quarantine_evidence.get(key,0)+1
        # ONLY research shadow evidence. SSE/SZSE ETF minimum quote tick is
        # 0.001 CNY; require each already-invalid current ETF OHLC field
        # within 0.00001 CNY of the 0.001 lattice. Never mutate any bar.
        try:
            prices=tuple(Decimal(str(x)) for x in (op,hi,lo,cl))
            tick=Decimal("0.001")
            lattice=tuple(x.quantize(tick,rounding=ROUND_HALF_UP) for x in prices)
            within_grid=all(abs(raw-rounded)<=Decimal("0.00001")
                            for raw,rounded in zip(prices,lattice))
        except (InvalidOperation, ValueError, OverflowError):
            lattice=()
            within_grid=False
        if not within_grid:
            category="ETF_TICK_LATTICE_FAR"
        else:
            category="ETF_TICK_LATTICE_NEAR"
            oq,hq,lq,cq=lattice
            if hq>=max(oq,cq,lq) and lq<=min(oq,cq,hq):
                repair="ETF_LATTICE_QUANTIZE_WOULD_ENCLOSE_BODY"
                quarantine_evidence[repair]=quarantine_evidence.get(repair,0)+1
        quarantine_evidence[category]=quarantine_evidence.get(category,0)+1
    if timeframe not in _ALLOWED_PERIODS:
        raise ValueError("unsupported period")
    if now_utc.tzinfo is None:
        raise ValueError("naive clock")
    if isinstance(frame, dict):
        # The official SDK's as_dataframe=False compact schema is columnar.
        # tickflow[realtime] does NOT install optional pandas; do not require
        # it in an AWS service or silently assume a DataFrame/DatetimeIndex.
        # The installed SDK explicitly permits missing "amount" and the
        # DataFrame helper silently fills it with zero. Never invent turnover:
        # preserve None + availability UNKNOWN on the research-only route.
        required = ("timestamp", "open", "high", "low", "close", "volume")
        if any(not isinstance(frame.get(key), (list, tuple)) for key in required):
            raise ValueError("missing compact SDK column")
        amount_present = "amount" in frame
        keys = (*required, "amount") if amount_present else required
        if amount_present and not isinstance(frame["amount"], (list,tuple)):
            raise ValueError("missing compact SDK column")
        sizes = {len(frame[key]) for key in keys}
        if len(sizes) != 1:
            raise ValueError("compact SDK column lengths differ")
        count = sizes.pop()
        minimum_rows = 1 if timeframe == "60m" else 4
        if count < minimum_rows:
            raise ValueError("insufficient history")
        if count > _ALLOWED_PERIODS[timeframe]:
            raise ValueError("history exceeds configured bound")
        records = [{**{key:frame[key][i] for key in keys},
                    **({} if amount_present else {"amount":None,"_sdk_amount_omitted":True})}
                   for i in range(count)]
    elif hasattr(frame, "to_dict"):
        records = frame.to_dict(orient="records")
    else:
        raise ValueError("unexpected SDK data type")
    if not isinstance(records, list):
        raise ValueError("unexpected SDK data type")
    minimum_rows = 1 if timeframe == "60m" else 4
    if len(records) < minimum_rows:
        raise ValueError("insufficient history")
    if len(records) > _ALLOWED_PERIODS[timeframe]:
        raise ValueError("history exceeds configured bound")
    bars=[]
    previous=None
    for raw in records:
        if not isinstance(raw, dict):
            raise ValueError("non-dict record")
        stamp=_select_timestamp(raw)
        if previous is not None and stamp<=previous:
            raise ValueError("reordered/duplicate timestamp")
        previous=stamp
        sh=stamp.astimezone(CN)
        current_shanghai_day = sh.date() == now_utc.astimezone(CN).date()
        if timeframe == "1d" and current_shanghai_day and not _post_close_research_eligible(stamp, now_utc):
            # A daily row dated 00:00 is NOT closed just because its
            # calendar label has elapsed. Never expose it before 15:02.
            quarantine("TODAY_DAILY_NOT_POSTCLOSE")
            continue
        if sh.second != 0 or sh.microsecond or sh.strftime("%H:%M") not in _LABEL_END[timeframe]:
            if current_shanghai_day:
                # Current provider response can contain a *forming* candle
                # labeled by its opening time (e.g. 13:00). Never turn it
                # into a historical BAR_END observation. Quarantine only this
                # session; historical off-grid labels remain a hard failure.
                quarantine("TODAY_LABEL_OFF_GRID")
                continue
            raise ValueError("unexpected Shanghai regular-session grid")
        # Reject future bars, but do not pretend already elapsed means exchange-final.
        if stamp > now_utc:
            # The provider can label a still-forming 15m/60m candle by the
            # future end boundary. Drop it from research output, not all bars.
            # A future trading *date* cannot be explained by a forming bar.
            if sh.date() != now_utc.astimezone(CN).date():
                raise ValueError("future trading date")
            quarantine("TODAY_FUTURE_LABEL")
            continue
        try:
            op=_number(raw,"open","open_price")
            hi=_number(raw,"high","high_price")
            lo=_number(raw,"low","low_price")
            cl=_number(raw,"close","close_price")
            vol=_number(raw,"volume","vol")
            amount_unknown = raw.get("_sdk_amount_omitted") is True
            amt = None if amount_unknown else _number(raw,"amount","turnover")
        except ValueError:
            if current_shanghai_day:
                # An unfinished today's bar can have missing quotes/turnover;
                # never backfill invented OHLC or claim it is a closed bar.
                # Historical invalid rows remain a fail-closed hard error.
                quarantine("TODAY_NONNUMERIC_OR_MISSING_VALUE")
                continue
            raise
        invalid_reason=None
        if op <= 0 or cl <= 0 or lo <= 0 or hi <= 0:
            invalid_reason="invalid OHLCVA nonpositive"
        elif hi < max(op,cl,lo):
            invalid_reason="invalid OHLCVA high below body"
        elif lo > min(op,cl,hi):
            invalid_reason="invalid OHLCVA low above body"
        elif vol < 0:
            invalid_reason="invalid OHLCVA negative volume"
        elif amt is not None and amt < 0:
            invalid_reason="invalid OHLCVA negative amount"
        ohlc_validation="STRICT"
        if invalid_reason is not None:
            # Official TickFlow October 13 contract: tolerate only a
            # non-mutating <= 1e-5 absolute float serialization gap.
            # This is OHLC shape only, NOT exchange finality, currentness
            # or canonical/source admission.
            float_only=(invalid_reason in (
                "invalid OHLCVA high below body",
                "invalid OHLCVA low above body")
                and vol >= 0 and (amt is None or amt >= 0)
                and _vendor_ohlc_float_gap_bucket(op,hi,lo,cl)
                    == "WITHIN_1E_MINUS_5"
                # Lattice validity is REQUIRED for both historical and
                # same-day vendor-float exceptions; a tiny body gap alone
                # does not qualify an off-tick historical OHLC value.
                and _vendor_etf_tick_lattice_shape_valid(op,hi,lo,cl)
                and (not current_shanghai_day or (
                    _post_close_research_eligible(stamp, now_utc)
                    or (
                        timeframe in ("5m","15m","60m")
                        and stamp <= now_utc - timedelta(seconds=90)
                    )
                )))
            if float_only:
                # Post-close same-day *historical-only* exception is gated
                # again in the reader; never grant session_currentness,
                # closure or any Radar admission. Preserve vendor floats.
                ohlc_validation="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
            else:
                if current_shanghai_day:
                    # Still quarantine all genuinely malformed current bars.
                    summarize_invalid_ohlc(op,hi,lo,cl,invalid_reason)
                    quarantine({
                        "invalid OHLCVA nonpositive":"TODAY_NONPOSITIVE_OHLC",
                        "invalid OHLCVA high below body":"TODAY_HIGH_BELOW_BODY",
                        "invalid OHLCVA low above body":"TODAY_LOW_ABOVE_BODY",
                        "invalid OHLCVA negative volume":"TODAY_NEGATIVE_VOLUME",
                        "invalid OHLCVA negative amount":"TODAY_NEGATIVE_AMOUNT",
                    }[invalid_reason])
                    continue
                rejection=ValueError(invalid_reason)
                if invalid_reason in ("invalid OHLCVA high below body",
                                      "invalid OHLCVA low above body"):
                    rejection._tickflow_ohlc_float_gap_bucket=(
                        _vendor_ohlc_float_gap_bucket(op,hi,lo,cl)
                    )
                raise rejection
        bars.append({
            "label": sh.strftime("%Y-%m-%d %H:%M"),
            "open":op,"high":hi,"low":lo,"close":cl,
            "volume":vol,"amount":amt,
            "amount_availability":"SDK_OMITTED" if amount_unknown else "PRESENT_UNVERIFIED",
            "is_partial_bar": True,
            "bar_finality": "NOT_VERIFIED",
            "ohlc_validation":ohlc_validation,
        })
    minimum_bars = 1 if timeframe == "60m" else 4
    if len(bars)<minimum_bars:
        raise ValueError("no sufficient historical closed-time candidates")
    return bars

def _expected_closed_grid_label(now_utc: datetime, timeframe: str) -> datetime | None:
    """Return last scheduled A-share BAR_END label due, not finality evidence.

    The 90s grace addresses ordinary provider publishing delay; if a due
    Shanghai session boundary is absent, label progression is not ready for
    live research. No exchange calendar is available: weekdays on holidays
    intentionally fail closed rather than invent an open market.
    """
    sh_now=now_utc.astimezone(CN)
    if sh_now.weekday()>=5:
        return None
    cutoff=sh_now-timedelta(seconds=90)
    if timeframe == "1d" and (sh_now.hour,sh_now.minute) < (15,2):
        return None
    candidates=[]
    for clock in _LABEL_END[timeframe]:
        hour,minute=map(int,clock.split(":"))
        proposed=sh_now.replace(hour=hour,minute=minute,second=0,microsecond=0)
        if proposed<=cutoff and proposed.date()==sh_now.date():
            candidates.append(proposed)
    return max(candidates) if candidates else None


def build_observation(client: Any, *, now_utc: datetime, repo_sha: str, sequence: int,
                      symbols: tuple[str,...]=SYMBOLS,
                      include_supplemental: bool=False,
                      allow_scan_symbols: bool=False,
                      use_batch: bool=False) -> dict:
    if now_utc.tzinfo is None or not re.fullmatch("[0-9a-f]{40}",repo_sha):
        raise ValueError("invalid wall clock or source revision")
    if type(sequence) is not int or sequence < 1:
        raise ValueError("invalid monotonic sequence")
    approved = (set(SYMBOLS) if not allow_scan_symbols else None)
    if (not symbols or len(symbols)>MAX_SCAN_SYMBOLS
            or len(set(symbols))!=len(symbols)
            or any(not isinstance(x,str) or not _SYMBOL_RE.fullmatch(x)
                   or (approved is not None and x not in approved)
                   for x in symbols)):
        raise ValueError("unapproved symbols")
    if type(include_supplemental) is not bool:
        raise ValueError("invalid supplemental timeframe flag")
    output={}
    periods=(_ALLOWED_PERIODS if include_supplemental
             else {"15m":96,"60m":24})
    if type(use_batch) is not bool:
        raise ValueError("invalid batch mode flag")
    period_symbols={period: symbols for period in periods}
    if include_supplemental and allow_scan_symbols:
        # Short periods are diagnostic QC only. Keep them on the approved
        # core set so sparse data from an arbitrary scan symbol cannot fail
        # the whole historical backtest snapshot.
        qc_symbols=tuple(symbol for symbol in symbols if symbol in SYMBOLS)
        period_symbols.pop("1m", None)
        period_symbols.pop("5m", None)
        if qc_symbols:
            period_symbols["1m"]=qc_symbols
            period_symbols["5m"]=qc_symbols
        period_symbols={period: period_symbols[period] for period in periods
                        if period in period_symbols}
    if use_batch:
        # The installed SDK contract defaults to 100 symbols per request.
        # Keep the scan ceiling at 200 while letting the SDK split each
        # timeframe into bounded batches instead of passing an unsupported
        # 200-symbol request size.
        try:
            configured_batch_size = int(os.environ.get("TICKFLOW_BATCH_SIZE", "100"))
        except ValueError:
            configured_batch_size = 100
        batch_size = min(len(symbols), max(1, min(configured_batch_size, 100)))
        client = type("_BatchClient", (), {
            "klines": _BatchKlinesFacade(
                client, period_symbols, periods, batch_size=batch_size,
            ),
        })()
    for index,symbol in enumerate(symbols):
        frames={}
        for interval, n in periods.items():
            if symbol not in period_symbols.get(interval, ()):
                frames[interval]={"status":"QC_ONLY_NOT_COLLECTED","rows":[]}
                continue
            # SDK's isolated Premium Kline contract was separately verified on AWS.
            stage=f"S{index}_{interval.upper()}_FETCH"
            try:
                frame=client.klines.get(symbol, period=interval,count=n,
                                        adjust="none",as_dataframe=False)
            except Exception as exc:
                exc._tickflow_stage=stage
                raise
            stage=f"S{index}_{interval.upper()}_NORMALIZE"
            try:
                if isinstance(frame,dict):
                    columns={key:value for key,value in frame.items()
                             if isinstance(value,(list,tuple))}
                    sizes={len(value) for value in columns.values()}
                    if len(sizes)==1 and sizes and next(iter(sizes))>n:
                        frame={key:(list(value)[-n:] if key in columns else value)
                               for key,value in frame.items()}
                elif hasattr(frame,"tail"):
                    frame=frame.tail(n)
                reasons={}
                evidence={}
                bars=normalize_bars(frame,interval,now_utc=now_utc,
                                    quarantine_counts=reasons,
                                    quarantine_evidence=evidence)
                # Some SDK responses may contain more rows than the requested
                # count. Keep the bounded, newest window requested by the
                # caller so one oversized response cannot invalidate the
                # complete bounded snapshot at publish time.
                bars=bars[-n:]
            except Exception as exc:
                # A bounded expanded scan may include newly listed or
                # illiquid symbols with fewer than four historical rows.
                # Preserve valid sibling symbols, but never hide a gap in the
                # fixed core set used for held-symbol validation.
                if (allow_scan_symbols and symbol not in SYMBOLS
                        and type(exc) is ValueError
                        and str(exc) == "insufficient history"):
                    frames[interval] = {
                        "status": "NO_DATA",
                        "period_availability": "INSUFFICIENT_HISTORY",
                        "rows": [],
                    }
                    continue
                exc._tickflow_stage=stage
                raise
            frames[interval]={"rows":bars,
                 "quarantine_reason_counts":reasons,
                 "quarantine_ohlc_gap_evidence":evidence,
                 "quarantined_unverified_rows_count":(
                     len(frame["timestamp"])-len(bars)
                     if isinstance(frame,dict) and isinstance(frame.get("timestamp"),list)
                     else 0
                 ),
                 "timestamp_semantic":("DATE_LABEL_UNPROVEN_CLOSE" if interval=="1d"
                    else "BAR_END_GRID_MATCH_HISTORICAL_ONLY"),
                 "currentness":"UNPROVEN", "closure":"NOT_VERIFIED",
                 "volume_units":"NOT_VERIFIED",
                 "adjustment":"NOT_VERIFIED","crosscheck":"NOT_VERIFIED"}
        output[symbol]=frames
    return {
        "schema":SCHEMA, "repo_sha":repo_sha, "provider":_SOURCE,
        "observed_at_utc":now_utc.astimezone(timezone.utc).isoformat(),
        "sequence":sequence, "status":"PASS_RESEARCH_ONLY",
        "symbols":output,"provider_first_target":True,
        "source_arbiter_admission":"BLOCKED","radar_admission":"BLOCKED",
        "canonical_write_authorized":False,"can_confirm_signal":False,
        "research_only":True,"live_trade":False,
    }

def atomic_publish(path: str, payload: dict) -> None:
    # Never publish a JSON blob that the strict reader and AWS auditor will
    # reject as oversized. Validate before opening or replacing any file.
    encoded=json.dumps(payload,allow_nan=False,separators=(",",":"))
    if len(encoded.encode("utf-8"))>MAX_BYTES:
        raise ValueError("private research cache exceeds bounded bytes")
    parent=Path(path).parent
    parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        fd,temporary=tempfile.mkstemp(prefix=".observation-",dir=parent)
        if hasattr(os, 'fchmod'):
            os.fchmod(fd,0o600)
        else:
            os.chmod(temporary,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            f.write(encoded)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)

def read_cn_tickflow_research_data(symbol: str, timeframe: str="15m", limit:int=30,
             *, path: str=DEFAULT_PATH, now_utc:datetime|None=None,
             research_mode: str="session_progress", observation:dict|None=None) -> dict:
    """Bounded research-only read, with explicitly separate historical mode.

    session_progress requires the last due intraday BAR_END label; historical
    permits verified-shape prior bars even if the current session is missing.
    Neither mode asserts exchange finality or source/Radar eligibility.
    """
    base={
        "ok":False,"provider":_SOURCE,"provider_first_target":True,
        "research_only":True, "bar_finality":"NOT_VERIFIED",
        "currentness":"UNPROVEN", "source_arbiter_admission":"BLOCKED",
        "radar_admission":"BLOCKED","live_trade":False,"can_confirm_signal":False,
        "canonical_write_authorized":False, "provider_requests":0,"cache_rejection_reason":"NONE",
        "research_mode":research_mode if research_mode in
            ("session_progress","historical_only") else "INVALID",
        "exchange_bar_finality":"NOT_VERIFIED",
    }
    def invalid_cache(reason: str) -> dict:
        # Fixed enum only: never expose raw cache values, labels or exceptions.
        return {**base,"status":"INVALID_CACHE",
                "cache_rejection_reason":reason}
    if (not isinstance(symbol,str) or not _SYMBOL_RE.fullmatch(symbol)
            or timeframe not in _ALLOWED_PERIODS
            or research_mode not in ("session_progress","historical_only")
            or (timeframe=="1d" and research_mode!="historical_only")
            or type(limit)!=int or not 1<=limit<=240):
        return {**base,"status":"INVALID_REQUEST"}
    try:
        # A worker may validate several frames from one atomically loaded
        # observation. All provenance/row checks below remain identical.
        if observation is None:
            with open(path,"rb") as f:
                data=f.read(MAX_BYTES+1)
            if len(data)>MAX_BYTES:
                return invalid_cache("CACHE_SIZE_EXCEEDED")
            obj=json.loads(data)
        else:
            obj=observation
    except (OSError,ValueError,TypeError,UnicodeError):
        return {**base,"status":"NO_DATA"}
    if not isinstance(obj, dict):
        return invalid_cache("CACHE_ROOT_INVALID")
    if obj.get("schema") != SCHEMA:
        return invalid_cache("CACHE_SCHEMA_MISMATCH")
    if obj.get("provider") != _SOURCE:
        return invalid_cache("CACHE_PROVIDER_MISMATCH")
    if obj.get("status") != "PASS_RESEARCH_ONLY":
        return invalid_cache("CACHE_STATUS_MISMATCH")
    if not (obj.get("research_only") is True and obj.get("radar_admission")=="BLOCKED" and obj.get("source_arbiter_admission")=="BLOCKED" and obj.get("live_trade") is False and obj.get("canonical_write_authorized") is False and obj.get("can_confirm_signal") is False):
        return invalid_cache("CACHE_SAFETY_FLAGS_INVALID")
    sha=obj.get("repo_sha")
    if not isinstance(sha,str) or not re.fullmatch("[0-9a-f]{40}",sha):
        return invalid_cache("CACHE_REPO_SHA_INVALID")
    try:
        now=now_utc or datetime.now(timezone.utc)
        observed=datetime.fromisoformat(obj["observed_at_utc"])
        if now.tzinfo is None or observed.tzinfo is None:
            raise ValueError
        age=(now-observed).total_seconds()
    except (ValueError,TypeError,KeyError,OverflowError):
        return invalid_cache("CACHE_OBSERVED_AT_INVALID")
    # Strict live-session provenance never inherits the slower off-hours
    # refresh schedule. Historical-only read gets a 6m bounded tolerance
    # after close (collector polls every 300s), or 18m on weekends (900s).
    # A 6m old snapshot is NOT represented as fresh/current live data.
    sh_now=now.astimezone(CN)
    historical_max_age=1080 if sh_now.weekday()>=5 else 360
    post_close_progress = (
        research_mode == "session_progress"
        and sh_now.weekday() < 5
        and (sh_now.hour, sh_now.minute) >= (15, 2)
    )
    max_age=(historical_max_age if research_mode=="historical_only"
             or post_close_progress else MAX_AGE_SECONDS)
    if age < -5 or age > max_age:
        return {**base,"status":"STALE","cache_rejection_reason":"CACHE_STALE","age_seconds":round(age,2),
                "max_age_seconds":max_age}
    cached_symbols = obj.get("symbols")
    if not isinstance(cached_symbols, dict) or symbol not in cached_symbols:
        return {**base,"status":"INVALID_REQUEST"}
    websocket_evidence = obj.get("websocket_evidence")
    if websocket_evidence is not None:
        ws_symbols = (websocket_evidence.get("symbols")
                      if isinstance(websocket_evidence, dict) else None)
        if (not isinstance(websocket_evidence, dict)
                or websocket_evidence.get("schema") != "stock_razor_tickflow_ws_research_evidence_v0_1"
                or not isinstance(ws_symbols, list)
                or ws_symbols != sorted(ws_symbols)
                or not all(isinstance(value, str) for value in ws_symbols)
                or not set(ws_symbols).issubset(cached_symbols)
                or websocket_evidence.get("subscription_ack") != "NOT_OBSERVABLE_VIA_OFFICIAL_SYNC_SDK"
                or websocket_evidence.get("continuous_feed_qualified") is not False
                or websocket_evidence.get("bar_finality") != "NOT_VERIFIED"
                or websocket_evidence.get("radar_admission") != "BLOCKED"
                or websocket_evidence.get("source_arbiter_admission") != "BLOCKED"
                or websocket_evidence.get("live_trade") is not False):
            return invalid_cache("WEBSOCKET_EVIDENCE_INVALID")
        for name in ("quote_callbacks", "quote_events", "initial_snapshot_candidates",
                     "post_initial_update_candidates", "duplicate_timestamp_events",
                     "out_of_order_timestamp_events", "unrequested_symbol_events",
                     "invalid_timestamp_events", "error_callbacks", "post_initial_lag_samples"):
            value = websocket_evidence.get(name)
            if type(value) is not int or value < 0:
                return invalid_cache("WEBSOCKET_EVIDENCE_COUNTER_INVALID")
        if websocket_evidence.get("post_initial_lag_bucket") not in {
                "NOT_VERIFIED", "UNDER_2S", "TWO_TO_FIVE_S", "FIVE_TO_THIRTY_S", "OVER_THIRTY_S"}:
            return invalid_cache("WEBSOCKET_EVIDENCE_LAG_INVALID")
    reject_reason="FRAME_OR_PERIOD_MISSING"
    try:
        raw=cached_symbols[symbol][timeframe]
        if isinstance(raw,dict) and raw.get("status")=="NO_DATA":
            if (symbol in SYMBOLS
                    or set(raw) != {"status", "period_availability", "rows"}
                    or raw.get("period_availability")!="INSUFFICIENT_HISTORY"
                    or raw.get("rows")!=[]):
                return invalid_cache("FRAME_NO_DATA_INVALID")
            return {**base,"status":"NO_DATA",
                    "period_availability":"INSUFFICIENT_HISTORY"}
        if (isinstance(raw,dict)
                and raw.get("status")=="QC_ONLY_NOT_COLLECTED"
                and timeframe in ("1m","5m")):
            return {**base,"status":"NO_DATA",
                    "cache_rejection_reason":"QC_PERIOD_NOT_COLLECTED"}
        rows=raw["rows"]
        reject_reason="BAR_COUNT_INVALID"
        minimum_rows = 1 if timeframe == "60m" and research_mode == "session_progress" else 4
        if not isinstance(rows,list) or not minimum_rows<=len(rows)<=_ALLOWED_PERIODS[timeframe]:
            raise ValueError
        reject_reason="FRAME_METADATA_INVALID"
        if raw.get("closure")!="NOT_VERIFIED" or raw.get("currentness")!="UNPROVEN":
            raise ValueError
        safe=[]
        previous=None
        # Validate the entire bounded cache, not only the requested tail. A
        # limit=1 client must not conceal earlier gaps or poisoned records.
        for item in rows:
            reject_reason="BAR_RECORD_INVALID"
            if not isinstance(item,dict) or item.get("bar_finality")!="NOT_VERIFIED" or item.get("is_partial_bar") is not True:
                raise ValueError
            label=item.get("label")
            reject_reason="BAR_LABEL_INVALID"
            if not isinstance(label,str):
                raise ValueError
            reject_reason="BAR_TIMESTAMP_INVALID"
            bar_stamp=datetime.strptime(label,"%Y-%m-%d %H:%M").replace(tzinfo=CN)
            reject_reason="BAR_TIME_GRID_OR_FUTURE_INVALID"
            if bar_stamp.strftime("%H:%M") not in _LABEL_END[timeframe] or bar_stamp.astimezone(timezone.utc)>now:
                raise ValueError
            reject_reason="BAR_ORDER_INVALID"
            if previous is not None and bar_stamp<=previous:
                raise ValueError
            previous=bar_stamp
            reject_reason="BAR_NUMERIC_VALUE_INVALID"
            numerical={}
            for key in ("open","high","low","close","volume"):
                val=item.get(key)
                if type(val) not in (int,float) or not isfinite(val):
                    raise ValueError
                numerical[key]=val
            reject_reason="BAR_AMOUNT_INVALID"
            availability=item.get("amount_availability")
            amount=item.get("amount")
            if availability=="SDK_OMITTED" and amount is None:
                numerical["amount"]=None
            elif availability=="PRESENT_UNVERIFIED" and type(amount) in (int,float) and isfinite(amount) and amount>=0:
                numerical["amount"]=amount
            else:
                raise ValueError
            reject_reason="BAR_OHLC_INVALID"
            op,hi,lo,cl=(numerical[k] for k in ("open","high","low","close"))
            shape_gap=(hi<max(op,cl,lo) or lo>min(op,cl,hi))
            tolerance=item.get("ohlc_validation","STRICT")
            if (min(op,hi,lo,cl)<=0 or numerical["volume"]<0
                    or tolerance not in (
                        "STRICT","VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY")
                    or (shape_gap and (
                        tolerance!="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
                        or _vendor_ohlc_float_gap_bucket(op,hi,lo,cl)
                            !="WITHIN_1E_MINUS_5"
                        or not _vendor_etf_tick_lattice_shape_valid(op,hi,lo,cl)
                        or (bar_stamp.date()==now.astimezone(CN).date()
                            and not (
                                # After the Shanghai close, session_progress
                                # remains a read-only due-grid view. It may
                                # accept the same bounded post-close vendor
                                # float evidence as historical_only, while
                                # keeping finality/currentness unproven.
                                ((research_mode in ("historical_only", "session_progress"))
                                 and _post_close_research_eligible(bar_stamp, now))
                                or (research_mode=="session_progress"
                                    and timeframe in ("5m","15m","60m")
                                    and (now.astimezone(CN).hour,
                                         now.astimezone(CN).minute)<(15,2)
                                    and bar_stamp.astimezone(timezone.utc)
                                        <= now-timedelta(seconds=90))
                            ))))
                    or (not shape_gap and tolerance!="STRICT")):
                raise ValueError
            safe.append({"label":label,**numerical,"amount_availability":availability,
                "is_partial_bar":True,"bar_finality":"NOT_VERIFIED",
                "ohlc_validation":tolerance})
    except (KeyError,ValueError,TypeError,OverflowError):
        return invalid_cache(reject_reason)
    # Rows are bounded by the collector contract (<=144); retain the whole
    # verified label grid for session continuity, then trim public output.
    validated_labels = {item["label"] for item in safe}
    safe = safe[-limit:]
    # Never present non-mutating vendor precision as strict OHLC.
    tolerated_rows=sum(
        1 for row in safe if
        row.get("ohlc_validation")=="VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY"
    )
    expected=_expected_closed_grid_label(now,timeframe)
    latest=bar_stamp
    progress="NOT_DUE_OR_NO_SESSION_CALENDAR"
    if expected is not None:
        # Reaching the last scheduled boundary is NOT sufficient: a source
        # can omit 10:00 while reporting 10:15. Check every due current-day
        # boundary (including morning when reading in the afternoon).
        due_labels = {
            expected.replace(hour=int(clock[:2]), minute=int(clock[3:]),
                             second=0, microsecond=0).strftime("%Y-%m-%d %H:%M")
            for clock in _LABEL_END[timeframe]
            if expected.replace(hour=int(clock[:2]), minute=int(clock[3:]),
                                second=0, microsecond=0) <= expected
        }
        missing_due_grid = not due_labels.issubset(validated_labels)
        if research_mode=="session_progress" and (
                latest < expected or missing_due_grid):
            # A freshly rewritten cache with a new last bar but earlier
            # missing due labels cannot be declared continuous research.
            return {
                **base, "status":"BAR_LABEL_BEHIND_SESSION",
                "source_age_seconds":round(age,2),
                "expected_grid_progress":"NOT_OBSERVED",
                "due_grid_continuity":"INCOMPLETE",
                "bar_finality":"NOT_VERIFIED",
                "rows":[],
            }
        if latest < expected:
            progress="DUE_LABEL_NOT_OBSERVED_HISTORICAL_ONLY"
        elif missing_due_grid:
            progress="DUE_LABEL_PRESENT_WITH_GAPS_HISTORICAL_ONLY"
        else:
            progress="DUE_LABEL_PRESENT_NOT_FINALITY_PROOF"
    label_age=(now-latest.astimezone(timezone.utc)).total_seconds()
    if research_mode=="historical_only":
        # Stated as limited historical use, never an eligible live provider.
        return {
            **base,"ok":True,"status":"PASS_HISTORICAL_ONLY","repo_sha":sha,
            "expected_grid_progress":progress,
            "last_bar_end_label_age_seconds":round(max(0,label_age),2),
            "latency_scope":"BAR_END_LABEL_AGE_NOT_PROVIDER_LATENCY",
            "max_age_seconds":max_age,
            "sequence":obj.get("sequence"),"source_age_seconds":round(age,2),
            "symbol":symbol,"timeframe":timeframe,"rows":safe,
            "ohlc_precision_scope":(
                "VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY" if tolerated_rows
                else "STRICT"
            ),
            "tolerated_vendor_float_rows":tolerated_rows,
            "timestamp_semantic":"BAR_END_GRID_MATCH_HISTORICAL_ONLY",
            "volume_units":"NOT_VERIFIED","crosscheck":"NOT_VERIFIED",
            "currentness":"UNPROVEN","session_currentness":"NOT_VERIFIED",
            "websocket_evidence":websocket_evidence,
        }
    return {
        **base,"ok":True,"status":"PASS_RESEARCH_ONLY","repo_sha":sha,
        "expected_grid_progress":progress,
        "last_bar_end_label_age_seconds":round(max(0,label_age),2),
        "latency_scope":"BAR_END_LABEL_AGE_NOT_PROVIDER_LATENCY",
        "max_age_seconds":max_age,
        "sequence":obj.get("sequence"),"source_age_seconds":round(age,2),
        "symbol":symbol,"timeframe":timeframe,"rows":safe,
        "ohlc_precision_scope":(
            "VENDOR_FLOAT_TOLERANCE_RESEARCH_ONLY" if tolerated_rows
            else "STRICT"
        ),
        "tolerated_vendor_float_rows":tolerated_rows,
        "timestamp_semantic":"BAR_END_GRID_MATCH_HISTORICAL_ONLY",
        "volume_units":"NOT_VERIFIED","crosscheck":"NOT_VERIFIED",
        "websocket_evidence":websocket_evidence,
    }


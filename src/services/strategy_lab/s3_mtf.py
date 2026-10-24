"""Offline S3 hypotheses. No provider, scheduler, broker or admission changes.

An explicit exchange schedule and a complete five-minute execution grid are
required. Five-minute bars model fills only, never the strategy signal. Raw
historical arrival/revision evidence remains the caller's data qualification.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from types import SimpleNamespace
import math

import numpy as np
import pandas as pd


OHLCV = ["open", "high", "low", "close", "volume"]
ARMS = {"A": (60, "legacy_adapter", 60), "B": (240, "pullback", 60), "C": (240, "retest", 60),
        "D": (240, "pullback", 240), "E": (120, "pullback", 60)}


@dataclass(frozen=True)
class Rules:
    daily_filter: str = "50_200"
    confirmation: str = "prior_high"
    stop_mode: str = "hybrid"
    exit_mode: str = "2R"
    first_risk_fraction: float = .4
    risk_fraction: float = .0025
    open_risk_cap: float = .0075
    sector_risk_cap: float = .005
    symbol_cap: float = .2
    gross_cap: float = .6
    max_positions: int = 3
    max_sector_positions: int = 2
    max_sessions: int = 50

    def __post_init__(self):
        if self.daily_filter not in {"50_200", "50_slope"}:
            raise ValueError("INVALID_DAILY_FILTER")
        if self.confirmation not in {"prior_high", "two_high"}:
            raise ValueError("INVALID_CONFIRMATION")
        if self.stop_mode not in {"hybrid", "structure", "atr"}:
            raise ValueError("INVALID_STOP_MODE")
        if self.exit_mode not in {"2R", "structure_trail"}:
            raise ValueError("INVALID_EXIT_MODE")
        if not 0 < self.first_risk_fraction <= 1:
            raise ValueError("INVALID_RISK_SPLIT")
        if not 0 < self.risk_fraction <= self.sector_risk_cap <= self.open_risk_cap < 1:
            raise ValueError("INVALID_RISK_CAPS")
        if not 0 < self.symbol_cap <= self.gross_cap <= 1:
            raise ValueError("INVALID_NOTIONAL_CAPS")
        if any(isinstance(x, bool) or not isinstance(x, int) or x < 1
               for x in (self.max_positions, self.max_sector_positions, self.max_sessions)):
            raise ValueError("INVALID_COUNT_CAPS")


def _aware(series):
    # Normalized capture frames already have a timezone-aware datetime dtype.
    # Avoid allocating one Python Timestamp for each of millions of raw rows.
    if isinstance(getattr(series, "dtype", None), pd.DatetimeTZDtype):
        result = pd.DatetimeIndex(series)
        if result.hasnans:
            raise ValueError("EXPLICIT_TIMESTAMP_OFFSET_REQUIRED")
        return result.tz_convert("UTC")
    values = [pd.Timestamp(x) for x in series]
    if any(x.tzinfo is None or pd.isna(x) for x in values):
        raise ValueError("EXPLICIT_TIMESTAMP_OFFSET_REQUIRED")
    return pd.DatetimeIndex(values).tz_convert("UTC")


_FIVE_NS = pd.Timedelta(minutes=5).value


def _session_grid(s):
    opens, closes = s.open_at.array.as_unit("ns").asi8, s.close_at.array.as_unit("ns").asi8
    duration = closes - opens
    if ((duration <= 0).any() or (duration % _FIVE_NS).any()
            or (duration > 78 * _FIVE_NS).any()):
        raise ValueError("INVALID_RTH_SESSION")
    if len(s) > 1 and (opens[1:] <= closes[:-1]).any():
        raise ValueError("OVERLAPPING_SESSIONS")
    counts = duration // _FIVE_NS
    offsets = np.r_[0, np.cumsum(counts)]
    within = np.arange(offsets[-1]) - np.repeat(offsets[:-1], counts) + 1
    grid = np.repeat(opens, counts) + within * _FIVE_NS
    return grid, counts, offsets


def validate_input(bars: pd.DataFrame, schedule: pd.DataFrame):
    """Fail the scenario on any missing path, including an entire missing day.

    The caller supplies the intended listing/coverage window in the schedule;
    coverage is never inferred by selecting future-complete trading paths.
    """
    b, s = bars.copy(), schedule.copy()
    if b.empty or s.empty:
        raise ValueError("EMPTY_INPUT")
    b["end"] = _aware(b.end)
    for key in OHLCV:
        b[key] = pd.to_numeric(b[key], errors="raise")
    for key in ("open_at", "close_at"):
        s[key] = _aware(s[key])
    if (not b.end.is_monotonic_increasing or b.end.duplicated().any()
            or not s.open_at.is_monotonic_increasing or s.open_at.duplicated().any()):
        raise ValueError("DUPLICATE_OR_UNORDERED_INPUT")
    expected, _, _ = _session_grid(s)
    if not np.array_equal(b.end.array.as_unit("ns").asi8, expected):
        raise ValueError("INCOMPLETE_OR_OFF_GRID_EXECUTION_PATH")
    values = b[OHLCV].to_numpy(dtype=float)
    if (not np.isfinite(values).all() or (values[:, :4] <= 0).any()
            or (values[:, 4] < 0).any()
            or (values[:, 1] < np.maximum.reduce([values[:, 0], values[:, 3], values[:, 2]])).any()
            or (values[:, 2] > np.minimum.reduce([values[:, 0], values[:, 3], values[:, 1]])).any()):
        raise ValueError("INVALID_OHLCV")
    return b.reset_index(drop=True), s.reset_index(drop=True)


def _aggregate_validated(b, s, minutes):
    """Aggregate disjoint array slices after the complete grid has been checked."""
    _, counts, offsets = _session_grid(s)
    step = minutes // 5
    starts = np.concatenate([np.arange(a, a+n, step, dtype=np.int64)
                             for a, n in zip(offsets[:-1], counts)])
    ends = np.r_[starts[1:], len(b)]
    times = pd.DatetimeIndex(b.end)
    start_times = times[starts] - pd.Timedelta(minutes=5)
    end_times = times[ends-1]
    duration = ((end_times.as_unit("ns").asi8-start_times.as_unit("ns").asi8)//pd.Timedelta(minutes=1).value).astype(int)
    opening, high, low, closing = (b[k].to_numpy(dtype=float) for k in OHLCV[:4])
    volume = b.volume.to_numpy()
    # Match the old per-bin numpy sum order, including non-integer volume.
    volumes = np.array([float(volume[a:z].sum()) for a, z in zip(starts, ends)])
    return pd.DataFrame(dict(start=start_times, end=end_times,
        available_at=end_times+pd.Timedelta(seconds=1),
        session=np.searchsorted(offsets[1:], starts, side="right"),
        duration_minutes=duration, stub=duration < minutes,
        open=opening[starts], high=np.maximum.reduceat(high, starts),
        low=np.minimum.reduceat(low, starts), close=closing[ends-1], volume=volumes))


def aggregate(bars, schedule, minutes):
    """RTH bins anchored to each actual session open; retain labelled stubs.

    Normal day: H4=[09:30,13:30),[13:30,16:00). The second bar is
    150 minutes, not a fictitious full H4. Early closes and DST come from
    the explicit schedule. This is a research convention, not native OpenD H4.
    """
    if minutes not in {15, 60, 120, 240, 390}:
        raise ValueError("UNSUPPORTED_PERIOD")
    b, s = validate_input(bars, schedule)
    return _aggregate_validated(b, s, minutes)


def features(frame):
    x = frame.copy()
    for n in (20, 50, 200):
        x[f"sma{n}"] = x.close.rolling(n, min_periods=n).mean()
    x["ema20"] = x.close.ewm(span=20, adjust=False, min_periods=20).mean()
    tr = pd.concat([x.high - x.low, (x.high - x.close.shift()).abs(),
                    (x.low - x.close.shift()).abs()], axis=1).max(axis=1)
    # True range, explicitly an arithmetic ATR14 (not Wilder smoothing).
    x["atr14"] = tr.rolling(14, min_periods=14).mean()
    x["prior_high20"] = x.high.rolling(20).max().shift()
    return x


def _fingerprint(frame, columns):
    values = pd.util.hash_pandas_object(frame[columns], index=True).to_numpy()
    return hashlib.sha256(values.tobytes()).digest()


class PreparedReplay:
    """Explicit validated snapshot; cache reuse rejects changed caller inputs.

    Price/feature snapshots never depend on rules, costs or replay boundaries.
    Historical completeness is checked before constructing any feature.
    """
    def __init__(self, inputs, schedule):
        if not inputs:
            raise ValueError("INVALID_REPLAY_ARGUMENT")
        self.signatures = {k:_fingerprint(v, ["end", *OHLCV]) for k,v in inputs.items()}
        self.schedule_signature = _fingerprint(schedule, ["open_at", "close_at"])
        self.raw = {}
        for k, frame in inputs.items():
            normalized, normalized_schedule = validate_input(frame, schedule)
            self.raw[k] = normalized
        self.schedule = normalized_schedule
        self.timeline = pd.DatetimeIndex(next(iter(self.raw.values())).end)
        if any(not pd.DatetimeIndex(x.end).equals(self.timeline) for x in self.raw.values()):
            raise ValueError("PORTFOLIO_GRID_MISMATCH")
        self.arrays = {k:{c:x[c].to_numpy(dtype=float, copy=True) for c in OHLCV}
                       for k,x in self.raw.items()}
        self.frames = {}
        self.feature_arrays = {}
        self.known = {}
        for k, frame in self.raw.items():
            for width in (60, 120, 240, 390):
                f = features(_aggregate_validated(frame, self.schedule, width))
                if width == 390:
                    f["sma50_lag10"] = f.sma50.shift(10)
                self.frames[k,width] = f
                self.feature_arrays[k,width] = {c:f[c].array for c in f.columns}
                self.known[k,width] = f.available_at.searchsorted(
                    self.timeline+pd.Timedelta(seconds=1), side="right")-1
        self.sessions = self.schedule.close_at.searchsorted(self.timeline-pd.Timedelta(minutes=5))
        self.session_closes = pd.DatetimeIndex(self.schedule.close_at)

    def check(self, inputs, schedule):
        if (set(inputs) != set(self.raw)
                or _fingerprint(schedule, ["open_at", "close_at"]) != self.schedule_signature
                or any(_fingerprint(inputs[k], ["end", *OHLCV]) != signature
                       for k,signature in self.signatures.items())):
            raise ValueError("PREPARED_INPUT_CHANGED")


def prepare_replay(inputs, schedule):
    """Validate once and cache all causal feature frames for repeated scenarios."""
    return PreparedReplay(inputs, schedule)


def daily_allowed(d, rules):
    if rules.daily_filter == "50_200":
        return bool(d.close > d.sma50 > d.sma200)
    return bool(d.close > d.sma50 and d.sma50 > d.sma50_lag10)


def build_signals(bars, schedule, arm, rules=Rules(), *, prepared=None, symbol=None,
                  matched_2h=False):
    """Build original arms, or an explicit time-matched E research control.

    E_TIME_MATCHED_SHARED_H4_ATR doubles structure lookback counts and freezes
    the latest *already available* H4 ATR at setup creation. Stubs mean this is
    not an exact economic-time or information-equivalence experiment. Original
    arms and their one-hour execution/ATR semantics remain unchanged by default.
    """
    if not isinstance(matched_2h, bool) or (matched_2h and arm != "E"):
        raise ValueError("MATCHED_2H_REQUIRES_ARM_E_AND_BOOLEAN_FLAG")
    if arm == "A":
        raise ValueError("A_BLOCKED_USE_EXPLICIT_ORIGINAL_S3_LEGACY_ADAPTER")
    if arm not in ARMS:
        raise ValueError("UNKNOWN_ARM")
    width, model, execution_width = ARMS[arm]
    if prepared is None:
        checked, checked_schedule = validate_input(bars, schedule)
        d = features(_aggregate_validated(checked, checked_schedule, 390))
        d["sma50_lag10"] = d.sma50.shift(10)
        h = features(_aggregate_validated(checked, checked_schedule, width))
        e = features(_aggregate_validated(checked, checked_schedule, execution_width)) if execution_width != width else h
    else:
        if symbol not in prepared.raw:
            raise ValueError("PREPARED_SYMBOL_REQUIRED")
        if (_fingerprint(bars, ["end", *OHLCV]) != prepared.signatures[symbol]
                or _fingerprint(schedule, ["open_at", "close_at"]) != prepared.schedule_signature):
            raise ValueError("PREPARED_INPUT_CHANGED")
        d, h, e = (prepared.frames[symbol,w] for w in (390, width, execution_width))
    if matched_2h:
        # Copy only E's structure frame; never mutate shared cached features.
        h = h.copy()
        h["ema20"] = h.close.ewm(span=40, adjust=False, min_periods=40).mean()
        h["sma50"] = h.close.rolling(100, min_periods=100).mean()
        h4 = (prepared.frames[symbol,240] if prepared is not None
              else features(_aggregate_validated(checked, checked_schedule, 240)))
        h4_asof = h4.available_at.searchsorted(h.available_at, side="right")-1
        h4_rows = list(h4.itertuples(index=False))
    slope_lag, decline_lag, floor_count, expiry_count, minimum_hi = (
        (6, 2, 6, 6, 106) if matched_2h else (3, 1, 3, 3, 53))
    dr, hr = list(d.itertuples(index=False)), list(h.itertuples(index=False))
    high_values = e.high.to_numpy()
    di = hi = -1
    setup = None
    signals = []
    for i, b in enumerate(e.itertuples()):
        while di + 1 < len(d) and dr[di + 1].available_at <= b.available_at:
            di += 1
        allowed = di >= 199 and daily_allowed(dr[di], rules)
        if not allowed:
            setup = None
        while hi + 1 < len(h) and hr[hi + 1].available_at <= b.available_at:
            hi += 1
            a = hr[hi]
            if setup and (hi > setup["expires"] or a.close < setup["floor"]):
                setup = None
            if not allowed or hi < minimum_hi:
                continue
            trend = a.ema20 > a.sma50 and a.sma50 > hr[hi - slope_lag].sma50
            if model == "pullback":
                falling = a.close < hr[hi - decline_lag].close < hr[hi - 2*decline_lag].close
                if setup is None and trend and falling and a.low <= a.ema20 and a.close >= a.sma50:
                    if matched_2h:
                        known_h4 = int(h4_asof[hi])
                        if known_h4 < 0:
                            continue
                        atr_row = h4_rows[known_h4]
                        if not math.isfinite(atr_row.atr14) or atr_row.atr14 <= 0:
                            continue
                        structure_atr = float(atr_row.atr14)
                    else:
                        structure_atr = float(a.atr14)
                    setup = dict(created=a.available_at, expires=hi + expiry_count,
                                 floor=min(x.low for x in hr[hi-floor_count+1:hi+1]),
                                 atr=structure_atr, ready=a.available_at, setup_end=a.end)
                    if matched_2h:
                        setup.update(atr_end=atr_row.end, atr_available_at=atr_row.available_at)
            else:
                if setup and setup.get("breakout") and a.available_at > setup["created"]:
                    level = setup["level"]
                    if a.low < level - .5 * setup["atr"] or a.close < level:
                        setup = None
                    elif a.low <= level + .25 * setup["atr"]:
                        setup.update(ready=a.available_at, floor=float(a.low), breakout=False)
                if setup is None and a.close > a.prior_high20 + .1 * a.atr14:
                    setup = dict(created=a.available_at, expires=hi + 3, floor=float(a.prior_high20 - .5*a.atr14),
                                 level=float(a.prior_high20), atr=float(a.atr14), ready=None,
                                 breakout=True, setup_end=a.end)
        if not allowed or setup is None or setup["ready"] is None or i < 14:
            continue
        # No confirmation from inside the setup/retest bar itself.
        if b.available_at <= setup["ready"] or b.start < setup["ready"] - pd.Timedelta(seconds=1):
            continue
        if b.close < setup["floor"]:
            setup = None
            continue
        lookback = 1 if rules.confirmation == "prior_high" else 2
        if not (b.close > float(high_values[i-lookback:i].max()) and b.close > b.open):
            continue
        structural = setup["floor"] - .25 * setup["atr"]
        atr_stop = b.close - 2 * b.atr14
        stop = {"structure": structural, "atr": atr_stop, "hybrid": min(structural, atr_stop)}[rules.stop_mode]
        if not math.isfinite(stop) or not 0 < stop < b.close:
            continue
        signals.append(dict(decision_at=b.available_at, signal_end=b.end, setup_end=setup["setup_end"],
                            d1_end=dr[di].end, structure_end=hr[hi].end, signal_close=b.close,
                            stop=stop, max_entry=b.close + .25*b.atr14, arm=arm))
        if matched_2h:
            signals[-1].update(structure_atr_end=setup["atr_end"],
                               structure_atr_available_at=setup["atr_available_at"])
        setup = None
    columns = ["decision_at", "signal_end", "setup_end", "d1_end",
               "structure_end", "signal_close", "stop", "max_entry", "arm"]
    if matched_2h:
        columns += ["structure_atr_end", "structure_atr_available_at"]
    return pd.DataFrame(signals, columns=columns)


def planned_loss(entry, stop, cost_rate):
    if not all(math.isfinite(x) for x in (entry, stop, cost_rate)) or not 0 < stop < entry or cost_rate < 0:
        raise ValueError("INVALID_PLANNED_LOSS")
    return entry * (1 + cost_rate) - stop * (1 - cost_rate)


def replay(inputs, schedule, signals, sectors, *, rules=Rules(), cost_bps=10., initial=100000.,
           trade_start=None, trade_end=None, prepared=None, max_holding_bars=None,
           exit_on_daily_filter=True):
    """One chronological portfolio. Stops win ambiguous bars; no future outcomes.

    inputs: symbol -> complete raw end-labelled 5m frame on identical schedule.
    signals: symbol -> build_signals output, already filtered to test window.
    Added leg has the same stop and a frozen campaign budget. No risk recycling.
    Execution fills the first 5m OPEN strictly after decision availability.
    """
    if not inputs or initial <= 0 or not math.isfinite(initial) or not math.isfinite(cost_bps) or cost_bps < 0:
        raise ValueError("INVALID_REPLAY_ARGUMENT")
    if set(inputs) != set(signals) or set(inputs) != set(sectors):
        raise ValueError("SYMBOL_SET_MISMATCH")
    if max_holding_bars is not None and (isinstance(max_holding_bars,bool)
            or not isinstance(max_holding_bars,int) or max_holding_bars < 1):
        raise ValueError("INVALID_HOLDING_BAR_CAP")
    if not isinstance(exit_on_daily_filter,bool):
        raise ValueError("INVALID_DAILY_EXIT_SWITCH")
    if prepared is None:
        prepared = prepare_replay(inputs, schedule)
    else:
        prepared.check(inputs, schedule)
    arrays = prepared.arrays
    full_timeline = prepared.timeline
    left = full_timeline[0]-pd.Timedelta(minutes=5) if trade_start is None else pd.Timestamp(trade_start)
    right = full_timeline[-1] if trade_end is None else pd.Timestamp(trade_end)
    if left.tzinfo is None or right.tzinfo is None or left >= right:
        raise ValueError("INVALID_REPLAY_WINDOW")
    indices = np.flatnonzero((full_timeline-pd.Timedelta(minutes=5) >= left) & (full_timeline <= right))
    if not len(indices):
        raise ValueError("EMPTY_REPLAY_WINDOW")
    timeline = full_timeline[indices]
    rate = cost_bps / 10000
    cash, active, closed, events, curve = initial, {}, [], [], []
    entry_queue = {}
    for sym, ss in signals.items():
        for signal in ss.to_dict("records"):
            ts = pd.Timestamp(signal["decision_at"])
            if ts.tzinfo is None or ts <= pd.Timestamp(signal["signal_end"]):
                raise ValueError("SIGNAL_CAUSAL_CLOCK_INVALID")
            if signal.get("arm") not in ARMS:
                raise ValueError("UNKNOWN_ARM")
            for key in ("d1_end", "structure_end", "setup_end"):
                evidence = pd.Timestamp(signal[key])
                if evidence.tzinfo is None or evidence + pd.Timedelta(seconds=1) > ts:
                    raise ValueError("FUTURE_OR_NAIVE_SIGNAL_EVIDENCE")
            if not all(math.isfinite(signal[key]) and signal[key] > 0
                       for key in ("stop", "signal_close", "max_entry")):
                raise ValueError("INVALID_SIGNAL_PRICES")
            if ts < left or ts > right:
                continue
            pos = timeline.searchsorted(ts + pd.Timedelta(minutes=5), side="left")
            if pos < len(timeline):
                entry_queue.setdefault(pos, []).append((sym, signal))
            else:
                events.append(dict(symbol=sym, time=ts, reason="NO_FUTURE_ENTRY"))
    row_cache = {}

    def past(sym, width, raw_index):
        idx = int(prepared.known[sym,width][raw_index])
        if idx < 0:
            return None
        key = (sym, width)
        cached = row_cache.get(key)
        if cached is None or cached[0] != idx:
            row = SimpleNamespace(**{c:values[idx] for c,values in prepared.feature_arrays[key].items()})
            row_cache[key] = idx, row
            return row
        return cached[1]

    add_queue, exit_queue = {}, {}

    def close(sym, price, when, reason):
        nonlocal cash
        p = active.pop(sym)
        cash += p["units"] * price * (1-rate)
        p.update(exit_at=when, exit_price=price, exit_reason=reason,
                 net_pnl=p["units"] * price * (1-rate) - p["cash_spent"])
        closed.append(p)

    for i, end in enumerate(timeline):
        start = end - pd.Timedelta(minutes=5)
        raw_index = indices[i]
        current_session = int(prepared.sessions[raw_index])
        # Resting stop has priority over a pending discretionary exit.
        for sym in sorted(list(active)):
            p = active[sym]
            opening = float(arrays[sym]["open"][raw_index])
            if opening <= p["stop"]:
                close(sym, opening, start, "GAP_STOP")
            elif rules.exit_mode == "2R" and opening >= p["target"]:
                close(sym, p["target"], start, "GAP_TARGET_LIMIT")
            elif sym in exit_queue and start >= exit_queue[sym]:
                close(sym, opening, start, "CLOSED_BAR_EXIT")
        exit_queue = {sym: ts for sym, ts in exit_queue.items() if sym in active and start < ts}
        needed_marks = set(active) | set(add_queue) | {sym for sym,_ in entry_queue.get(i, [])}
        marks = {sym:float(arrays[sym]["open"][raw_index]) for sym in needed_marks}

        def attempt(sym, signal=None, adding=False):
            nonlocal cash
            price = marks[sym]
            equity = cash + sum(p["units"]*marks[k] for k,p in active.items())
            gross = sum(p["units"]*marks[k] for k,p in active.items())
            sector = sectors[sym]
            p = active.get(sym)
            if adding:
                if p is None or p["added"]:
                    return
                stop, budget, max_entry = p["stop"], p["budget"], p["add_max_entry"]
            else:
                if p is not None:
                    events.append(dict(symbol=sym, time=start, reason="ALREADY_HELD"))
                    return
                stop, budget, max_entry = signal["stop"], equity*rules.risk_fraction, signal["max_entry"]
            reason = None
            if not 0 < stop < price:
                reason = "GAP_THROUGH_STOP"
            elif price > max_entry:
                reason = "CHASE_LIMIT"
            elif not adding and (len(active) >= rules.max_positions or sum(sectors[k] == sector for k in active) >= rules.max_sector_positions):
                reason = "POSITION_CAP"
            if reason:
                events.append(dict(symbol=sym, time=start, reason=reason))
                return
            risk_share = planned_loss(price, stop, rate)
            # Cumulative original-stop planned loss never decreases after a trail.
            total_risk = sum(a["risk_spent"] for a in active.values())
            sector_risk = sum(a["risk_spent"] for k,a in active.items() if sectors[k] == sector)
            spent = p["risk_spent"] if adding else 0.
            allowed = min(budget-spent if adding else budget*rules.first_risk_fraction,
                          equity*rules.open_risk_cap-total_risk,
                          equity*rules.sector_risk_cap-sector_risk)
            prior_notional = p["units"]*price if adding else 0.
            capacity = min(equity*rules.symbol_cap-prior_notional,
                           equity*rules.gross_cap-gross, cash/(1+rate))
            units = max(0, math.floor(min(allowed/risk_share, capacity/price)))
            if units < 1:
                events.append(dict(symbol=sym, time=start, reason="RISK_CASH_NOTIONAL_CAP"))
                return
            cash_spent, loss = units*price*(1+rate), units*risk_share
            cash -= cash_spent
            if adding:
                p["units"] += units
                p["cash_spent"] += cash_spent
                p["risk_spent"] += loss
                p["added"] = True
            else:
                active[sym] = dict(symbol=sym, entry_at=start, initial_entry=price,
                                   units=units, stop=stop, original_stop=stop, budget=budget,
                                   cash_spent=cash_spent, risk_spent=loss, added=False,
                                   target=price+2*(price-stop), reached_2r=False,
                                   entry_session=current_session,
                                   last_hour=None, arm=signal.get("arm", "UNKNOWN"))
                if max_holding_bars is not None:
                    active[sym]["entry_execution_index"] = i
            assert active[sym]["risk_spent"] <= budget + 1e-7
            assert cash >= -1e-7
            events.append(dict(symbol=sym, time=start, reason="ADD" if adding else "ENTRY", units=units,
                               price=price, cost_paid=units*price*rate, stop=stop,
                               leg_planned_loss=loss,
                               campaign_risk=active[sym]["risk_spent"], campaign_budget=budget))

        for sym, ts in sorted(add_queue.items()):
            if start >= ts:
                attempt(sym, adding=True)
        add_queue = {sym: ts for sym, ts in add_queue.items() if sym in active and start < ts}
        for sym, signal in sorted(entry_queue.get(i, []), key=lambda z:z[0]):
            attempt(sym, signal)
        for sym in sorted(list(active)):
            p = active[sym]
            if arrays[sym]["low"][raw_index] <= p["stop"]:
                close(sym, p["stop"], end, "STOP")
                continue
            if arrays[sym]["high"][raw_index] >= p["target"]:
                if rules.exit_mode == "2R":
                    close(sym, p["target"], end, "TARGET_2R")
                    continue
                p["reached_2r"] = True
            known_at = end + pd.Timedelta(seconds=1)
            structure_width, _, decision_width = ARMS.get(p["arm"], ARMS["B"])
            hour = past(sym, decision_width, raw_index)
            day = past(sym, 390, raw_index)
            if (current_session - p["entry_session"] + 1 >= rules.max_sessions
                    and end == prepared.session_closes[current_session]):
                exit_queue.setdefault(sym, known_at)
            if max_holding_bars is not None and i-p["entry_execution_index"]+1 >= max_holding_bars:
                exit_queue.setdefault(sym, known_at)
            if exit_on_daily_filter and day is not None and not daily_allowed(day, rules):
                exit_queue.setdefault(sym, known_at)
            if hour is not None and hour.end != p["last_hour"]:
                p["last_hour"] = hour.end
                if (not p["added"] and math.isfinite(hour.atr14) and hour.atr14 > 0
                        and hour.end > p["entry_at"]
                        and hour.close >= p["initial_entry"] + (p["initial_entry"]-p["original_stop"])):
                    p["add_max_entry"] = float(hour.close + .25*hour.atr14)
                    add_queue.setdefault(sym, known_at)
            if rules.exit_mode == "structure_trail" and p["reached_2r"]:
                struct = past(sym, structure_width, raw_index)
                if struct is not None and struct.close < struct.ema20:
                    exit_queue.setdefault(sym, known_at)
        equity = cash + sum(p["units"]*float(arrays[k]["close"][raw_index]) for k,p in active.items())
        curve.append(dict(end=end, equity=equity, cash=cash,
                          gross_exposure=(equity-cash)/equity))
    for sym in sorted(list(active)):
        close(sym, float(arrays[sym]["close"][indices[-1]]), timeline[-1], "SAMPLE_BOUNDARY")
    curve[-1].update(equity=cash, cash=cash, gross_exposure=0.)
    assert abs(cash-initial-sum(p["net_pnl"] for p in closed)) < 1e-6
    return pd.DataFrame(closed), pd.DataFrame(events), pd.DataFrame(curve)


def metrics(trades, curve, initial=100000.):
    if curve.empty:
        raise ValueError("EMPTY_EQUITY_CURVE")
    eq = curve.set_index("end").equity
    daily = eq.groupby(eq.index.tz_convert("America/New_York").date).last()
    ret = np.r_[daily.iloc[0]/initial-1, daily.pct_change().iloc[1:].to_numpy()]
    peak = np.maximum.accumulate(np.r_[initial, eq.to_numpy()])[1:]
    pnl = trades.net_pnl.to_numpy() if len(trades) else np.array([])
    wins, losses = pnl[pnl>0], pnl[pnl<0]
    years = (eq.index[-1]-(eq.index[0]-pd.Timedelta(minutes=5))).total_seconds() / (365.25*86400)
    below = daily.to_numpy() < np.maximum.accumulate(np.r_[initial, daily.to_numpy()])[1:]
    longest = run = 0
    for flag in below:
        run = run+1 if flag else 0
        longest = max(longest, run)
    return dict(total_return=float(eq.iloc[-1]/initial-1),
                cagr=float((eq.iloc[-1]/initial)**(1/years)-1) if years >= 1 and eq.iloc[-1]>0 else None,
                mdd=float(np.max(1-eq.to_numpy()/peak)),
                sharpe=float(np.mean(ret)/np.std(ret, ddof=1)*np.sqrt(252)) if len(ret)>1 and np.std(ret,ddof=1)>0 else None,
                profit_factor=float(wins.sum()/-losses.sum()) if len(losses) else None,
                win_rate=float(np.mean(pnl>0)) if len(pnl) else None,
                payoff_ratio=float(wins.mean()/-losses.mean()) if len(wins) and len(losses) else None,
                trades=len(pnl), average_holding_hours=float(((pd.to_datetime(trades.exit_at)-pd.to_datetime(trades.entry_at)).dt.total_seconds()/3600).mean()) if len(trades) else None,
                max_underwater_sessions=int(longest), unrecovered_at_end=bool(below[-1]),
                mean_gross_exposure=float(curve.gross_exposure.mean()),
                mdd_convention="5M_CLOSE_MARK_TO_MARKET", sharpe_risk_free_rate=0.,
                promotion="NO", TRADE_EXECUTION="NO")

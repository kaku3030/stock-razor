"""Offline S3 hypotheses. No provider, scheduler, broker or admission changes.

An explicit exchange schedule and a complete five-minute execution grid are
required. Five-minute bars model fills only, never the strategy signal. Raw
historical arrival/revision evidence remains the caller's data qualification.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd


OHLCV = ["open", "high", "low", "close", "volume"]
ARMS = {"B": (240, "pullback", 60), "C": (240, "retest", 60),
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
    values = [pd.Timestamp(x) for x in series]
    if any(x.tzinfo is None or pd.isna(x) for x in values):
        raise ValueError("EXPLICIT_TIMESTAMP_OFFSET_REQUIRED")
    return pd.DatetimeIndex(values).tz_convert("UTC")


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
    previous_close = None
    grid = []
    for r in s.itertuples():
        minutes = (r.close_at - r.open_at).total_seconds() / 60
        if minutes <= 0 or minutes % 5 or minutes > 390:
            raise ValueError("INVALID_RTH_SESSION")
        if previous_close is not None and r.open_at <= previous_close:
            raise ValueError("OVERLAPPING_SESSIONS")
        previous_close = r.close_at
        grid.extend(pd.date_range(r.open_at + pd.Timedelta(minutes=5), r.close_at, freq="5min"))
    expected = pd.DatetimeIndex(grid)
    if not pd.DatetimeIndex(b.end).equals(expected):
        raise ValueError("INCOMPLETE_OR_OFF_GRID_EXECUTION_PATH")
    values = b[OHLCV].to_numpy(dtype=float)
    if (not np.isfinite(values).all() or (values[:, :4] <= 0).any()
            or (values[:, 4] < 0).any()
            or (b.high < b[["open", "close", "low"]].max(axis=1)).any()
            or (b.low > b[["open", "close", "high"]].min(axis=1)).any()):
        raise ValueError("INVALID_OHLCV")
    return b.reset_index(drop=True), s.reset_index(drop=True)


def aggregate(bars, schedule, minutes):
    """RTH bins anchored to each actual session open; retain labelled stubs.

    Normal day: H4=[09:30,13:30),[13:30,16:00). The second bar is
    150 minutes, not a fictitious full H4. Early closes and DST come from
    the explicit schedule. This is a research convention, not native OpenD H4.
    """
    if minutes not in {15, 60, 120, 240, 390}:
        raise ValueError("UNSUPPORTED_PERIOD")
    b, s = validate_input(bars, schedule)
    rows = []
    for session, r in enumerate(s.itertuples()):
        part = b[(b.end > r.open_at) & (b.end <= r.close_at)]
        for start in pd.date_range(r.open_at, r.close_at, freq=f"{minutes}min", inclusive="left"):
            end = min(start + pd.Timedelta(minutes=minutes), r.close_at)
            x = part[(part.end > start) & (part.end <= end)]
            duration = int((end - start).total_seconds() / 60)
            rows.append(dict(start=start, end=end, available_at=end + pd.Timedelta(seconds=1),
                             session=session, duration_minutes=duration, stub=duration < minutes,
                             open=float(x.open.iloc[0]), high=float(x.high.max()), low=float(x.low.min()),
                             close=float(x.close.iloc[-1]), volume=float(x.volume.sum())))
    return pd.DataFrame(rows)


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


def daily_allowed(d, rules):
    if rules.daily_filter == "50_200":
        return bool(d.close > d.sma50 > d.sma200)
    return bool(d.close > d.sma50 and d.sma50 > d.sma50_lag10)


def build_signals(bars, schedule, arm, rules=Rules()):
    if arm == "A":
        raise ValueError("A_BLOCKED_NO_FROZEN_D1_H1_M15_RULE")
    if arm not in ARMS:
        raise ValueError("UNKNOWN_ARM")
    width, model, execution_width = ARMS[arm]
    d = features(aggregate(bars, schedule, 390))
    d["sma50_lag10"] = d.sma50.shift(10)
    h = features(aggregate(bars, schedule, width))
    e = features(aggregate(bars, schedule, execution_width)) if execution_width != width else h
    di = hi = -1
    setup = None
    signals = []
    for i, b in enumerate(e.itertuples()):
        while di + 1 < len(d) and d.available_at.iloc[di + 1] <= b.available_at:
            di += 1
        allowed = di >= 199 and daily_allowed(d.iloc[di], rules)
        if not allowed:
            setup = None
        while hi + 1 < len(h) and h.available_at.iloc[hi + 1] <= b.available_at:
            hi += 1
            a = h.iloc[hi]
            if setup and (hi > setup["expires"] or a.close < setup["floor"]):
                setup = None
            if not allowed or hi < 53:
                continue
            trend = a.ema20 > a.sma50 and a.sma50 > h.sma50.iloc[hi - 3]
            if model == "pullback":
                falling = a.close < h.close.iloc[hi - 1] < h.close.iloc[hi - 2]
                if setup is None and trend and falling and a.low <= a.ema20 and a.close >= a.sma50:
                    setup = dict(created=a.available_at, expires=hi + 3, floor=float(h.low.iloc[hi-2:hi+1].min()),
                                 atr=float(a.atr14), ready=a.available_at, setup_end=a.end)
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
        if not (b.close > float(e.high.iloc[i-lookback:i].max()) and b.close > b.open):
            continue
        structural = setup["floor"] - .25 * setup["atr"]
        atr_stop = b.close - 2 * b.atr14
        stop = {"structure": structural, "atr": atr_stop, "hybrid": min(structural, atr_stop)}[rules.stop_mode]
        if not math.isfinite(stop) or not 0 < stop < b.close:
            continue
        signals.append(dict(decision_at=b.available_at, signal_end=b.end, setup_end=setup["setup_end"],
                            d1_end=d.end.iloc[di], structure_end=h.end.iloc[hi], signal_close=b.close,
                            stop=stop, max_entry=b.close + .25*b.atr14, arm=arm))
        setup = None
    return pd.DataFrame(signals, columns=["decision_at", "signal_end", "setup_end", "d1_end",
                                         "structure_end", "signal_close", "stop", "max_entry", "arm"])


def planned_loss(entry, stop, cost_rate):
    if not all(math.isfinite(x) for x in (entry, stop, cost_rate)) or not 0 < stop < entry or cost_rate < 0:
        raise ValueError("INVALID_PLANNED_LOSS")
    return entry * (1 + cost_rate) - stop * (1 - cost_rate)


def replay(inputs, schedule, signals, sectors, *, rules=Rules(), cost_bps=10., initial=100000.,
           trade_start=None, trade_end=None):
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
    raw = {k: validate_input(v, schedule)[0] for k, v in inputs.items()}
    schedule = validate_input(next(iter(inputs.values())), schedule)[1]
    symbols = sorted(raw)
    full_timeline = pd.DatetimeIndex(raw[symbols[0]].end)
    if any(not pd.DatetimeIndex(x.end).equals(full_timeline) for x in raw.values()):
        raise ValueError("PORTFOLIO_GRID_MISMATCH")
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
    frames = {(sym, width): features(aggregate(b, schedule, width))
              for sym, b in raw.items() for width in (60, 120, 240)}
    daily = {sym: features(aggregate(b, schedule, 390)) for sym, b in raw.items()}
    for x in daily.values():
        x["sma50_lag10"] = x.sma50.shift(10)
    add_queue, exit_queue = {}, {}

    def close(sym, price, when, reason):
        nonlocal cash
        p = active.pop(sym)
        cash += p["units"] * price * (1-rate)
        p.update(exit_at=when, exit_price=price, exit_reason=reason,
                 net_pnl=p["units"] * price * (1-rate) - p["cash_spent"])
        closed.append(p)

    def past(frame, when):
        idx = frame.available_at.searchsorted(when, side="right") - 1
        return None if idx < 0 else frame.iloc[idx]

    for i, end in enumerate(timeline):
        start = end - pd.Timedelta(minutes=5)
        current = {sym: raw[sym].iloc[indices[i]] for sym in symbols}
        # Resting stop has priority over a pending discretionary exit.
        for sym in sorted(list(active)):
            p, b = active[sym], current[sym]
            if b.open <= p["stop"]:
                close(sym, float(b.open), start, "GAP_STOP")
            elif rules.exit_mode == "2R" and b.open >= p["target"]:
                close(sym, p["target"], start, "GAP_TARGET_LIMIT")
            elif sym in exit_queue and start >= exit_queue[sym]:
                close(sym, float(b.open), start, "CLOSED_BAR_EXIT")
        exit_queue = {sym: ts for sym, ts in exit_queue.items() if sym in active and start < ts}
        marks = {sym: float(b.open) for sym, b in current.items()}

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
                                   entry_session=int(schedule.close_at.searchsorted(start)),
                                   last_hour=None, arm=signal.get("arm", "UNKNOWN"))
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
            p, b = active[sym], current[sym]
            if b.low <= p["stop"]:
                close(sym, p["stop"], end, "STOP")
                continue
            if b.high >= p["target"]:
                if rules.exit_mode == "2R":
                    close(sym, p["target"], end, "TARGET_2R")
                    continue
                p["reached_2r"] = True
            known_at = end + pd.Timedelta(seconds=1)
            structure_width, _, decision_width = ARMS.get(p["arm"], ARMS["B"])
            hour = past(frames[sym, decision_width], known_at)
            day = past(daily[sym], known_at)
            current_session = int(schedule.close_at.searchsorted(start))
            if (current_session - p["entry_session"] + 1 >= rules.max_sessions
                    and end == schedule.close_at.iloc[current_session]):
                exit_queue.setdefault(sym, known_at)
            if day is not None and not daily_allowed(day, rules):
                exit_queue.setdefault(sym, known_at)
            if hour is not None and hour.end != p["last_hour"]:
                p["last_hour"] = hour.end
                if (not p["added"] and math.isfinite(hour.atr14) and hour.atr14 > 0
                        and hour.end > p["entry_at"]
                        and hour.close >= p["initial_entry"] + (p["initial_entry"]-p["original_stop"])):
                    p["add_max_entry"] = float(hour.close + .25*hour.atr14)
                    add_queue.setdefault(sym, known_at)
            if rules.exit_mode == "structure_trail" and p["reached_2r"]:
                struct = past(frames[sym, structure_width], known_at)
                if struct is not None and struct.close < struct.ema20:
                    exit_queue.setdefault(sym, known_at)
        equity = cash + sum(p["units"]*float(current[k].close) for k,p in active.items())
        curve.append(dict(end=end, equity=equity, cash=cash,
                          gross_exposure=(equity-cash)/equity))
    for sym in sorted(list(active)):
        close(sym, float(raw[sym].close.iloc[indices[-1]]), timeline[-1], "SAMPLE_BOUNDARY")
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

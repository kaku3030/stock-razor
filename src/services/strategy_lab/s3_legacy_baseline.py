"""Recovered S3 D1/H1 + SRVP baseline; offline research only.

The frozen strategy has TWO signal timeframes. Five-minute data only supplies
session-aware aggregation and the separate shared execution engine. Daily
context is aligned by actual end+1s availability, never by a same-day date.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .s3_mtf import OHLCV, _fingerprint, prepare_replay


LEGACY_SIGNAL_MODEL = "S3_LEGACY_D1_H1_SRVP_CAUSAL_CLOCK"
SOURCE_SHA256 = {
    "round10_radar_replay.py": "861ea467ac06ae5c31c822d601f2e597a6a68dc63dd5bf96c3a89ebadcfa559c",
    "round14_srvp_fusion.py": "87ad3d67dade19c000b476a90f62b1a90b438508fc78a46b14d8fe2e801378da",
    "round24_six_strategy_backtest.py": "c2fcd614bf45d9217e9d32f7f89424abda85704b26b9f74a813fe3217b696ee0",
}
COLUMNS = ["decision_at", "signal_end", "setup_end", "d1_end", "structure_end",
           "signal_close", "stop", "max_entry", "arm", "poc", "val", "vah",
           "legacy_signal_model", "h1_index", "srvp_pass", "d1_available_at"]


def legacy_profile(window):
    """Exact recovered 100-hour profile arithmetic: 21 bins, 70% value area.

    Covered-bin boundaries, POC-center convention and left-first tie handling
    intentionally preserve the frozen implementation, including equal endpoints.
    This is an OHLCV volume allocation approximation, not trade-level volume.
    """
    low, high = float(window.low.min()), float(window.high.max())
    if not np.isfinite([low, high]).all() or high <= low:
        return (np.nan,)*3
    edges = np.linspace(low, high, 22)
    volume = np.zeros(21)
    for row in window.itertuples():
        left = max(0, int(np.searchsorted(edges, row.low, side="right")-1))
        right = min(20, int(np.searchsorted(edges, row.high, side="left")))
        volume[left:right+1] += float(row.volume)/max(1, right-left+1)
    poc = int(np.argmax(volume))
    selected = {poc}
    target = float(volume.sum()*.70)
    while volume[list(selected)].sum() < target and (min(selected) > 0 or max(selected) < 20):
        left, right = min(selected)-1, max(selected)+1
        lv = volume[left] if left >= 0 else -1
        rv = volume[right] if right < 21 else -1
        selected.add(left if lv >= rv else right)
    return ((edges[poc]+edges[poc+1])/2,
            edges[min(selected)], edges[max(selected)+1])


def build_legacy_candidates(bars, schedule, *, prepared=None, symbol=None):
    """Return ALL cooled-down base candidates, retaining failed SRVP evidence.

    A failed SRVP observation consumes the same five-observed-H1 cooldown as a
    passed one. This ordering is essential to faithfully reproduce the baseline.
    Reuse an existing validated PreparedReplay to avoid repeated data preparation.
    """
    if prepared is None:
        symbol = symbol if symbol is not None else "LEGACY"
        prepared = prepare_replay({symbol:bars}, schedule)
    else:
        if symbol not in prepared.raw:
            raise ValueError("PREPARED_SYMBOL_REQUIRED")
        if (_fingerprint(bars, ["end", *OHLCV]) != prepared.signatures[symbol]
                or _fingerprint(schedule, ["open_at", "close_at"]) != prepared.schedule_signature):
            raise ValueError("PREPARED_INPUT_CHANGED")
    d, h = prepared.frames[symbol,390], prepared.frames[symbol,60]
    # Keep the original mean(high-low), not true range/ATR. The volume mean
    # includes the current signal bar, exactly as in the frozen strategy.
    prior_low20 = h.low.rolling(20).min().shift()
    mean_range20 = (h.high-h.low).rolling(20).mean()
    mean_volume20 = h.volume.rolling(20).mean()
    di = d.available_at.searchsorted(h.available_at, side="right")-1
    valid_daily = di >= 0
    safe_di = np.maximum(di, 0)
    dc, ma20, ma50 = (d[c].to_numpy()[safe_di] for c in ("close", "sma20", "sma50"))
    valid = (valid_daily & (dc > ma20) & (ma20 > ma50)
             & (h.close.to_numpy() > h.sma20.to_numpy())
             & (h.close.to_numpy() > h.prior_high20.to_numpy())
             & (h.volume.to_numpy() > 1.2*mean_volume20.to_numpy()))
    rows, last = [], -1000000
    for i in np.flatnonzero(valid):
        if i-last < 5:
            continue
        bar = h.iloc[i]
        stop = min(float(prior_low20.iloc[i]), float(bar.close)-1.5*float(mean_range20.iloc[i]))
        if not 0 < stop < bar.close:
            continue
        # The cooldown is spent BEFORE SRVP filtering, even when it fails.
        last = int(i)
        poc, val, vah = legacy_profile(h.iloc[i-100:i]) if i >= 100 else (np.nan,)*3
        passed = bool(np.isfinite([poc, val, vah]).all()
                      and bar.low <= val+.25*(vah-val)
                      and bar.close > val and bar.close > bar.open)
        daily = d.iloc[int(di[i])]
        rows.append(dict(decision_at=bar.available_at, signal_end=bar.end,
                         setup_end=bar.end, d1_end=daily.end, structure_end=bar.end,
                         signal_close=float(bar.close), stop=stop,
                         max_entry=np.finfo(float).max, arm="A", poc=poc, val=val, vah=vah,
                         legacy_signal_model=LEGACY_SIGNAL_MODEL, h1_index=int(i),
                         srvp_pass=passed, d1_available_at=daily.available_at))
    return pd.DataFrame(rows, columns=COLUMNS)


def build_legacy_signals(bars, schedule, *, prepared=None, symbol=None):
    """Return only genuine SRVP_ON entries; never label this a 15m strategy."""
    candidates = build_legacy_candidates(bars, schedule, prepared=prepared, symbol=symbol)
    return candidates.loc[candidates.srvp_pass.astype(bool)].reset_index(drop=True)

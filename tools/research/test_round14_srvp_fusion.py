from __future__ import annotations

import pandas as pd

from tools.research.round14_srvp_fusion import _confirmation_times, _profile


def test_profile_is_invalid_until_lookback_is_available():
    frame = pd.DataFrame({"low": [1.0], "high": [2.0], "volume": [10.0]})
    poc, val, vah = _profile(frame)
    assert 1.0 <= val <= poc <= vah <= 2.0


def test_15m_confirmation_uses_prior_completed_hour():
    h1 = pd.DataFrame({"time_key": pd.to_datetime(["2024-01-01 10:00"]), "open": [9.0], "high": [11.0], "low": [9.0], "close": [10.5], "volume": [100.0]})
    m15 = pd.DataFrame({"time_key": pd.to_datetime(["2024-01-01 10:15"]), "open": [10.0], "high": [11.0], "low": [9.5], "close": [10.8], "volume": [20.0]})
    out = _confirmation_times({"1H": h1, "15m": m15}, pd.Series(pd.to_datetime(["2024-01-01 10:15"])))
    assert not bool(out.loc[0, "srvp_15m_confirm"])

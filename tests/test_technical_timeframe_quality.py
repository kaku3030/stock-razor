"""Caller provisional evidence survives all indicator-history branches."""
import pandas as pd
import pytest

from src.technical.timeframe import analyze_timeframe


@pytest.mark.parametrize("count", [0, 4, 16, 30])
@pytest.mark.parametrize("partial", [False, True])
def test_partial_flag_survives_insufficient_and_missing_data(count, partial):
    frame = pd.DataFrame([
        {"date": f"2026-10-16 {9 + i // 60:02}:{i % 60:02}",
         "open": 1.5, "high": 1.7, "low": 1.3, "close": 1.6, "volume": 1000}
        for i in range(count)
    ])
    state = analyze_timeframe(frame, "1h", is_partial_bar=partial)
    assert state.quality.is_partial_bar is partial
    assert state.quality.bars == count
    if 0 < count < 20:
        assert "1h_insufficient_bars" in state.quality.warnings
        assert pd.Timestamp(state.quality.as_of) == pd.Timestamp(frame.iloc[-1]["date"])
        assert state.indicators == {}
        assert ("1h_partial_bar" in state.quality.warnings) is partial

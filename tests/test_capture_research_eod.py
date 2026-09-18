import sys
import types

import pandas as pd
import pytest

from scripts.capture_research_eod import capture_yfinance, main


OHLCV_FIELDS = ("Open", "High", "Low", "Close", "Volume")


def _fake_yfinance(monkeypatch, *, bad_field=None, bad_value=None):
    values = {"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.5, "Volume": 1000.0}
    if bad_field is not None:
        values[bad_field] = bad_value
    frame = pd.DataFrame(
        [values],
        index=pd.to_datetime(["2026-09-17"]),
    )
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        types.SimpleNamespace(download=lambda *args, **kwargs: frame),
    )


@pytest.mark.parametrize("field", OHLCV_FIELDS)
@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_capture_yfinance_rejects_nonfinite_ohlcv(monkeypatch, field, bad_value):
    _fake_yfinance(monkeypatch, bad_field=field, bad_value=bad_value)

    with pytest.raises(ValueError, match="non-finite"):
        capture_yfinance("AAPL", "2026-09-16", "2026-09-18")


@pytest.mark.parametrize("field", OHLCV_FIELDS)
def test_capture_yfinance_rejects_partial_final_bar(monkeypatch, field):
    _fake_yfinance(monkeypatch, bad_field=field, bad_value=None)

    with pytest.raises(ValueError, match="non-finite"):
        capture_yfinance("AAPL", "2026-09-16", "2026-09-18")


def test_main_blocks_capture_and_removes_csv_on_invalid_row(tmp_path, monkeypatch):
    _fake_yfinance(monkeypatch, bad_field="Close", bad_value=float("nan"))
    output = tmp_path / "us_AAPL.csv"
    output.write_text("stale output must not survive a blocked capture\n", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "capture_research_eod",
            "--market",
            "us",
            "--source",
            "yfinance",
            "--symbol",
            "AAPL",
            "--start",
            "2026-09-16",
            "--end",
            "2026-09-18",
            "--output",
            str(output),
            "--retries",
            "1",
        ],
    )

    assert main() == 2
    assert not output.exists()
    manifest = output.with_suffix(output.suffix + ".manifest.json")
    assert manifest.exists()
    assert '"status": "CAPTURE_BLOCKED"' in manifest.read_text(encoding="utf-8")

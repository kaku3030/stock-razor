"""Offline contract tests: benchmark cannot mutate subscriptions or trade."""
from pathlib import Path
import ast

from scripts.benchmark_opend_native_klines_readonly import percentile, quality_check


class Synthetic:
    def __init__(self, rows):
        self.rows = rows
    def to_dict(self, *, orient):
        assert orient == "records"
        return self.rows


def sample(label="2026-10-14 09:30:00"):
    return {"time_key": label, "open": 10., "high": 11.,
            "low": 9., "close": 10.5, "volume": 123.}


def test_open_d_quality_checks_and_empty_data_fails_closed():
    ok = quality_check(Synthetic([
        sample("2026-10-13 09:30:00"),
        sample("2026-10-13 09:31:00"),
    ]))
    assert ok["returned"] == 2 and ok["integrity"] == "PASS"
    assert quality_check(Synthetic([]))["integrity"] == "BLOCKED"
    duplicated = quality_check(Synthetic([sample(), sample()]))
    assert duplicated["duplicates"] == 1 and duplicated["integrity"] == "BLOCKED"
    invalid = sample()
    invalid["high"] = 2.
    assert quality_check(Synthetic([invalid]))["integrity"] == "BLOCKED"


def test_percentiles_do_not_invent_missing_measurements():
    assert percentile([], 95) is None
    assert percentile([100, 200, 300], 50) == 200
    assert percentile([100, 200, 300], 95) == 290


def test_code_does_not_subscribe_trade_or_query_historical_quota():
    source = Path("scripts/benchmark_opend_native_klines_readonly.py").read_text("utf8")
    code = ast.parse(source)
    names = {
        n.func.attr
        for n in ast.walk(code)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "get_cur_kline" in names
    assert "query_subscription" in names
    assert not {"subscribe", "unsubscribe", "place_order", "unlock_trade",
                "get_history_kline", "request_history_kline"} & names
    assert "MAX_CALLS = 65" in source

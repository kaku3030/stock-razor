"""Offline contract tests: benchmark cannot mutate subscriptions or trade."""
from pathlib import Path
import ast
import sys
from types import SimpleNamespace

from scripts import benchmark_opend_native_klines_readonly as benchmark

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


def fake_sdk(monkeypatch, current, *, ret=0):
    class Context:
        closed = False
        scopes = []
        calls = []

        def query_subscription(self, *, is_all_conn):
            self.scopes.append(is_all_conn)
            # The production connection has subscriptions. The new caller
            # must not use them as proof that its own requests are eligible.
            return ret, {"sub_list": {"1m": ["US.AMD", "US.QQQ"]}
                         if is_all_conn else current}

        def get_cur_kline(self, symbol, count, *, ktype, autype):
            self.calls.append((symbol, count, ktype))
            return 0, Synthetic([sample()])

        def close(self):
            self.closed = True

    ctx = Context()
    kinds = SimpleNamespace(K_1M="1m", K_5M="5m", K_15M="15m", K_60M="60m")
    monkeypatch.setitem(sys.modules, "futu", SimpleNamespace(
        OpenQuoteContext=lambda **kwargs: ctx, RET_OK=0,
        KLType=kinds, SubType=kinds, AuType=SimpleNamespace(NONE="none")))
    monkeypatch.setattr(benchmark, "sleep", lambda _: None)
    return ctx


def test_foreign_subscriptions_do_not_trigger_ineligible_kline_calls(monkeypatch):
    ctx = fake_sdk(monkeypatch, {})
    result = benchmark.main()
    assert ctx.scopes == [False]
    assert result["subscription_scope"] == "CURRENT_CONNECTION"
    assert result["status"] == "BLOCKED_NO_PREEXISTING_KLINE_SUBSCRIPTION"
    assert result["call_count"] == 0
    assert result["preexisting_symbol_timeframe_pairs"] == 0
    assert ctx.calls == [] and ctx.closed


def test_native_calls_use_only_owned_symbol_periods_and_close_context(monkeypatch):
    ctx = fake_sdk(monkeypatch, {"1m": ["US.AMD"]})
    result = benchmark.main()
    assert result["preexisting_symbol_timeframe_pairs"] == 1
    assert result["call_count"] == len(benchmark.COUNTS) + benchmark.REPEATS
    assert all(symbol == "US.AMD" and period == "1m"
               for symbol, _, period in ctx.calls)
    assert result["subscription_changes"] == 0 and ctx.closed


def test_subscription_discovery_failure_never_reads_klines(monkeypatch):
    ctx = fake_sdk(monkeypatch, {}, ret=-1)
    result = benchmark.main()
    assert result["status"] == "BLOCKED"
    assert result["subscription_discovery"] == "BLOCKED"
    assert result["call_count"] == 0
    assert ctx.calls == [] and ctx.closed

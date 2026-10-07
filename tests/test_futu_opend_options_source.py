from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.services.options_intelligence.futu_opend_source import (
    FutuOpenDOptionsSource,
)


ET = ZoneInfo("America/New_York")


class FakeQuoteContext:
    def __init__(self, *, host, port):
        self.host = host
        self.port = port
        self.closed = False
        self.snapshot_calls = []
        self.chain_calls = []

    def get_market_snapshot(self, codes):
        self.snapshot_calls.append(list(codes))
        if codes == ["US.QQQ"]:
            return 0, pd.DataFrame(
                [
                    {
                        "code": "US.QQQ",
                        "last_price": 760.0,
                        "prev_close_price": 756.2,
                        "update_time": "2026-10-07 10:00:00",
                    }
                ]
            )
        return 0, pd.DataFrame(
            [
                {
                    "code": code,
                    "option_valid": True,
                    "option_type": "CALL" if "C" in code[-7:] else "PUT",
                    "option_strike_price": 750.0,
                    "strike_time": "2026-10-09",
                    "option_open_interest": 100,
                    "option_gamma": 0.01,
                    "option_implied_volatility": 25.0,
                    "option_contract_multiplier": 100,
                    "update_time": "2026-10-07 10:00:00",
                }
                for code in codes
            ]
        )

    def get_option_chain(self, code, *, start, end):
        self.chain_calls.append((code, start, end))
        return 0, pd.DataFrame(
            [
                {"code": "US.QQQ261009C750000"},
                {"code": "US.QQQ261009P750000"},
                {"code": "US.QQQ261009C755000"},
            ]
        )

    def close(self):
        self.closed = True


def test_source_is_read_only_batched_and_closes_context():
    created = []

    def factory(**kwargs):
        ctx = FakeQuoteContext(**kwargs)
        created.append(ctx)
        return ctx

    now = datetime(2026, 10, 7, 10, 0, tzinfo=ET)
    with FutuOpenDOptionsSource(
        snapshot_batch_size=2,
        chain_days=7,
        quote_context_factory=factory,
    ) as source:
        fetched = source.fetch("QQQ", evaluated_at=now)

    ctx = created[0]
    assert ctx.closed is True
    assert fetched.symbol == "US.QQQ"
    assert fetched.chain_contracts == 3
    assert fetched.snapshot_contracts == 3
    assert ctx.snapshot_calls == [
        ["US.QQQ"],
        ["US.QQQ261009C750000", "US.QQQ261009P750000"],
        ["US.QQQ261009C755000"],
    ]
    assert ctx.chain_calls == [("US.QQQ", "2026-10-07", "2026-10-14")]


def test_source_requires_context_manager_before_fetch():
    source = FutuOpenDOptionsSource(
        quote_context_factory=lambda **kwargs: FakeQuoteContext(**kwargs)
    )

    with pytest.raises(RuntimeError, match="opened first"):
        source.fetch(
            "QQQ",
            evaluated_at=datetime(2026, 10, 7, 10, 0, tzinfo=ET),
        )


def test_source_rejects_invalid_limits():
    with pytest.raises(ValueError):
        FutuOpenDOptionsSource(snapshot_batch_size=201)
    with pytest.raises(ValueError):
        FutuOpenDOptionsSource(chain_days=46)
    with pytest.raises(ValueError):
        FutuOpenDOptionsSource(port=0)


def test_source_fails_closed_on_provider_error():
    class FailingContext(FakeQuoteContext):
        def get_option_chain(self, code, *, start, end):
            return -1, "permission denied"

    source = FutuOpenDOptionsSource(
        quote_context_factory=lambda **kwargs: FailingContext(**kwargs)
    )
    with source:
        with pytest.raises(RuntimeError, match="get_option_chain failed"):
            source.fetch(
                "QQQ",
                evaluated_at=datetime(2026, 10, 7, 10, 0, tzinfo=ET),
            )


def test_source_module_contains_no_trade_context_reference():
    from pathlib import Path
    import src.services.options_intelligence.futu_opend_source as module

    text = Path(module.__file__).read_text(encoding="utf-8")
    assert "OpenTradeContext" not in text
    assert "trade_context" not in text.lower()

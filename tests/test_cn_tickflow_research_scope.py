"""Offline PR #658 approved-scope regression evidence; zero provider I/O."""
from datetime import datetime, timezone

import pytest

from data_provider.cn_tickflow_research_cache import build_observation


@pytest.mark.parametrize("symbols", [
    ("600519.SH",), ("159611.SZ", "159611.SZ"), (), (None,),
    ("159611.SZ", "518880.SH", "600519.SH"),
])
def test_scope_rejected_before_provider_call(symbols):
    calls = []

    class Klines:
        def get(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise RuntimeError("SYNTHETIC_PROVIDER_BOUNDARY_REACHED")

    class Client:
        klines = Klines()

    with pytest.raises(ValueError, match="unapproved symbols"):
        build_observation(
            Client(), now_utc=datetime(2026, 10, 13, 5, tzinfo=timezone.utc),
            repo_sha="a" * 40, sequence=1, symbols=symbols,
        )
    assert calls == []


@pytest.mark.parametrize("symbols", [("159611.SZ",), ("518880.SH", "159611.SZ")])
def test_approved_unique_scope_reaches_provider(symbols):
    calls = []

    class Klines:
        def get(self, symbol, **kwargs):
            calls.append(symbol)
            raise RuntimeError("SYNTHETIC_PROVIDER_BOUNDARY_REACHED")

    class Client:
        klines = Klines()

    with pytest.raises(RuntimeError, match="SYNTHETIC_PROVIDER_BOUNDARY_REACHED"):
        build_observation(
            Client(), now_utc=datetime(2026, 10, 13, 5, tzinfo=timezone.utc),
            repo_sha="a" * 40, sequence=1, symbols=symbols,
        )
    assert calls == [symbols[0]]

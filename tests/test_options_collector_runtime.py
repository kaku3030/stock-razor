import json
from datetime import datetime
from zoneinfo import ZoneInfo

from src.services.options_intelligence.collector_runtime import (
    run_options_collection_cycle,
)
from src.services.options_intelligence.futu_opend_source import FutuOptionsFetch
from src.services.stock_radar_v2.options_context_reader import (
    RadarOptionsContextReader,
)


ET = ZoneInfo("America/New_York")
SHA = "d" * 40


def _fetch(symbol: str, *, quote_time: str) -> FutuOptionsFetch:
    root = symbol.removeprefix("US.")
    return FutuOptionsFetch(
        symbol=symbol,
        underlying_row={
            "code": symbol,
            "last_price": 760.0,
            "prev_close_price": 756.2,
            "update_time": "2026-10-07 10:00:00",
        },
        option_rows=(
            {
                "code": f"US.{root}261016C760000",
                "option_valid": True,
                "option_type": "CALL",
                "option_strike_price": 760.0,
                "strike_time": "2026-10-16",
                "option_open_interest": 1200,
                "option_gamma": 0.021,
                "option_implied_volatility": 25.0,
                "option_contract_multiplier": 100,
                "update_time": quote_time,
            },
            {
                "code": f"US.{root}261016P750000",
                "option_valid": True,
                "option_type": "PUT",
                "option_strike_price": 750.0,
                "strike_time": "2026-10-16",
                "option_open_interest": 900,
                "option_gamma": 0.019,
                "option_implied_volatility": 26.0,
                "option_contract_multiplier": 100,
                "update_time": quote_time,
            },
        ),
        chain_contracts=2,
        snapshot_contracts=2,
    )


class FakeSource:
    def __init__(self, *, quote_time="2026-10-07 09:59:00", fail_symbol=None):
        self.quote_time = quote_time
        self.fail_symbol = fail_symbol
        self.calls = []

    def fetch(self, symbol, *, evaluated_at):
        self.calls.append((symbol, evaluated_at))
        if symbol == self.fail_symbol:
            raise RuntimeError("synthetic source failure")
        return _fetch(symbol, quote_time=self.quote_time)


def test_cycle_writes_atomic_snapshot_consumable_by_radar_reader(tmp_path):
    now = datetime(2026, 10, 7, 10, 0, tzinfo=ET)
    source = FakeSource()
    output = tmp_path / "options-intelligence.json"

    result = run_options_collection_cycle(
        source,
        ["QQQ", "QQQ"],
        evaluated_at=now,
        runtime_instance_id="collector-1",
        repo_sha=SHA,
        sequence=1,
        output_path=output,
    )

    assert result.snapshot_written is True
    assert result.status == "DEGRADED_RESEARCH"
    assert result.packets_written == 1
    assert [call[0] for call in source.calls] == ["US.QQQ"]

    read = RadarOptionsContextReader(now=lambda: now).read_file(
        output,
        expected_repo_sha=SHA,
    )
    assert read.status == "PASS"
    context = read.by_symbol()["US.QQQ"]
    assert context.radar_admission == "CONTEXT_ONLY"
    assert context.decision_permission == "BLOCKED_V0_1"
    assert context.trading_authority is False


def test_non_trading_cycle_does_not_touch_provider_or_output(tmp_path):
    saturday = datetime(2026, 10, 10, 10, 0, tzinfo=ET)
    source = FakeSource()
    output = tmp_path / "options-intelligence.json"

    result = run_options_collection_cycle(
        source,
        ["QQQ"],
        evaluated_at=saturday,
        runtime_instance_id="collector-1",
        repo_sha=SHA,
        sequence=2,
        output_path=output,
    )

    assert result.status == "BLOCKED"
    assert result.snapshot_written is False
    assert source.calls == []
    assert not output.exists()


def test_partial_source_failure_writes_only_qualified_packets(tmp_path):
    now = datetime(2026, 10, 7, 10, 0, tzinfo=ET)
    source = FakeSource(fail_symbol="US.AMD")
    output = tmp_path / "options-intelligence.json"

    result = run_options_collection_cycle(
        source,
        ["QQQ", "AMD"],
        evaluated_at=now,
        runtime_instance_id="collector-1",
        repo_sha=SHA,
        sequence=3,
        output_path=output,
    )

    assert result.status == "DEGRADED_RESEARCH"
    assert result.snapshot_written is True
    assert result.packets_written == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert set(payload["symbols"]) == {"US.QQQ"}
    amd = next(item for item in result.symbol_results if item.symbol == "US.AMD")
    assert amd.packet is None
    assert amd.reasons == ("SOURCE_OR_QUALIFICATION_ERROR:RuntimeError",)


def test_all_stale_rows_do_not_overwrite_previous_snapshot(tmp_path):
    now = datetime(2026, 10, 7, 10, 0, tzinfo=ET)
    source = FakeSource(quote_time="2026-10-06 16:00:00")
    output = tmp_path / "options-intelligence.json"
    output.write_text('{"sentinel":"old"}', encoding="utf-8")

    result = run_options_collection_cycle(
        source,
        ["QQQ"],
        evaluated_at=now,
        runtime_instance_id="collector-1",
        repo_sha=SHA,
        sequence=4,
        output_path=output,
    )

    assert result.status == "BLOCKED"
    assert result.snapshot_written is False
    assert output.read_text(encoding="utf-8") == '{"sentinel":"old"}'


def test_postmarket_cycle_does_not_fetch_until_spot_semantics_are_qualified(tmp_path):
    after_close = datetime(2026, 10, 7, 17, 0, tzinfo=ET)
    source = FakeSource()

    result = run_options_collection_cycle(
        source,
        ["QQQ"],
        evaluated_at=after_close,
        runtime_instance_id="collector-1",
        repo_sha=SHA,
        sequence=5,
        output_path=tmp_path / "options.json",
    )

    assert result.status == "BLOCKED"
    assert source.calls == []
    assert "POSTMARKET_SPOT_SEMANTICS_NOT_QUALIFIED" in result.reasons

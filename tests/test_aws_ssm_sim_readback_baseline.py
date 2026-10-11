"""Static and offline executable tests for AWS SSM US-SIM-only readback.

The workflow owns the only OpenD I/O. Tests never start OpenD or AWS,
never query the user's real accounts, and never print sensitive rows.
"""

from datetime import datetime, timezone
from pathlib import Path
import textwrap


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/aws-ssm-sim-account-discovery.yml"
)


class Frame:
    columns = ("code", "qty")

    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return list(self.rows)

    def __len__(self):
        return len(self.rows)


class FutuMock:
    RET_OK = 0

    class TrdEnv:
        SIMULATE = "SIMULATE"

    class Currency:
        USD = "USD"


def _helpers():
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index("          def count_sim_us_rows(data):")
    end = source.index("\n          ctx = None", start)
    ns = {"ft": FutuMock, "datetime": datetime, "timezone": timezone}
    exec(compile(textwrap.dedent(source[start:end]), str(WORKFLOW), "exec"), ns)
    return ns


def _candidate(**overrides):
    row = {
        "acc_id": 12345,
        "trd_env": "SIMULATE",
        "sim_acc_type": "STOCK_AND_OPTION",
        "acc_status": "ACTIVE",
        "trdmarket_auth": ["US"],
    }
    row.update(overrides)
    return row


class TradeContextMock:
    def __init__(self, positions=4, orders=0, failing=None):
        self.calls = []
        self.positions = positions
        self.orders = orders
        self.failing = failing

    def _query(self, family, **kwargs):
        self.calls.append((family, kwargs))
        if family == self.failing:
            # No error payload may be propagated to the public workflow log.
            return -1, "secret raw broker error"
        length = {
            "balance": 1, "positions": self.positions,
            "orders": self.orders, "history": 0,
        }[family]
        return 0, Frame([{} for _ in range(length)])

    def accinfo_query(self, **kwargs):
        return self._query("balance", **kwargs)

    def position_list_query(self, **kwargs):
        return self._query("positions", **kwargs)

    def order_list_query(self, **kwargs):
        return self._query("orders", **kwargs)

    def history_order_list_query(self, **kwargs):
        return self._query("history", **kwargs)


def test_candidate_pin_ignores_real_account_even_when_first_row():
    functions = _helpers()
    rows = Frame([
        _candidate(acc_id=999, trd_env="REAL"),
        _candidate(acc_id=12345),
        _candidate(acc_id=888, sim_acc_type="FUTURES"),
        _candidate(acc_id=777, acc_status="DISABLED"),
    ])
    assert functions["count_sim_us_rows"](rows) == 1
    assert functions["select_us_sim_id"](rows) == 12345


def test_multiple_missing_or_malformed_sim_ids_fail_closed():
    select = _helpers()["select_us_sim_id"]
    assert select(Frame([_candidate(acc_id=123), _candidate(acc_id=234)])) is None
    assert select(Frame([_candidate(trd_env="REAL")])) is None
    assert select(Frame([_candidate(acc_id=True)])) is None
    assert select(Frame([_candidate(acc_id=0)])) is None
    assert select(Frame([_candidate(acc_id="INVALID_SECRET")])) is None
    assert select(Frame([_candidate(trdmarket_auth=["HK"])])) is None
    assert select(object()) is None


def test_only_pinned_simulate_account_is_ever_read_and_existing_holdings_reviewed():
    probe = _helpers()["read_sim_account_baseline"]
    client = TradeContextMock(positions=4)
    summary = probe(client, 12345)
    assert all(
        summary[family] == "PASS"
        for family in (
            "balance_readback", "positions_readback",
            "orders_readback", "history_readback",
        )
    )
    assert summary["position_review"] == "REQUIRED"
    assert summary["order_review"] == "NOT_REQUIRED"
    assert [item[0] for item in client.calls] == [
        "balance", "positions", "orders", "history"
    ]
    for _, kwargs in client.calls:
        assert kwargs["acc_id"] == 12345
        assert kwargs["trd_env"] == "SIMULATE"
        if "refresh_cache" in kwargs:
            assert kwargs["refresh_cache"] is False


def test_readback_failure_does_not_synthesize_positive_evidence():
    probe = _helpers()["read_sim_account_baseline"]
    for failing in ("balance", "positions", "orders", "history"):
        client = TradeContextMock(failing=failing)
        summary = probe(client, 12345)
        status_key = {
            "balance": "balance_readback", "positions": "positions_readback",
            "orders": "orders_readback", "history": "history_readback",
        }[failing]
        assert summary[status_key] == "UNAVAILABLE"
        assert "secret" not in str(summary)
        if failing == "positions":
            assert summary["position_review"] == "UNKNOWN"
        if failing == "orders":
            assert summary["order_review"] == "UNKNOWN"


def test_public_workflow_never_logs_raw_account_detail_or_promotes_paper():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "ft.TrdMarket.US" in source
    assert "ft.TrdEnv.SIMULATE" in source
    assert "sim_id = select_us_sim_id(data)" in source
    assert "if count == 1 and sim_id is not None:" in source
    assert "out.update(read_sim_account_baseline(ctx, sim_id))" in source
    assert '"sim_native_fills": "UNSUPPORTED_BY_OPEND"' in source
    assert '"paper_preflight": "BLOCKED"' in source
    assert '"paper_auto_ready": False' in source
    assert 'paper_auto_ready: false' in source
    assert "RADAR_ADMISSION=BLOCKED" in source
    assert "SOURCE_ARBITER_ADMISSION=BLOCKED" in source
    assert "LIVE_TRADE=NO" in source
    assert '--query StandardOutputContent --output text' in source
    assert 'echo "SIM_ACCOUNT_DISCOVERY_SUMMARY=$safe"' in source
    assert "place_order(" not in source
    assert "modify_order(" not in source
    assert "unlock_trade(" not in source
    assert "deal_list_query(" not in source
    assert "ft.TrdEnv.REAL" not in source
    assert "print(data)" not in source
    assert "out[\"acc_id\"]" not in source
    assert "out[\"cash\"]" not in source

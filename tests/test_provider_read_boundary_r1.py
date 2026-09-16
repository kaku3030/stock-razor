from datetime import date, datetime, timezone

import pytest

from src.services.live_feed.provider_read_boundary_r1 import (
    AccountListParams, FakeReadWorker, HistoryKlineParams, PositionListParams,
    ProviderExecutionOutcome, ProviderReadRequest, ProviderReadOutcome,
    QuoteSnapshotParams, ReadOperation, TradingDaysParams,
)


def req(op, params, rid="r1"):
    return ProviderReadRequest("rt", "fake", rid, op, datetime(2026, 1, 1, tzinfo=timezone.utc), params)


def test_typed_allowlist_and_immutable_identity():
    r = req(ReadOperation.QUOTE_SNAPSHOT, QuoteSnapshotParams(("AAPL",)))
    assert r.operation is ReadOperation.QUOTE_SNAPSHOT
    with pytest.raises(TypeError): req("call", {})
    with pytest.raises(TypeError): req(ReadOperation.QUOTE_SNAPSHOT, AccountListParams())


@pytest.mark.parametrize("outcome", list(ProviderExecutionOutcome))
def test_replay_matrix_terminal_facts_are_deterministic(outcome):
    worker = FakeReadWorker(); r = req(ReadOperation.HISTORY_KLINE,
        HistoryKlineParams("AAPL", "1d", date(2020, 1, 1), date(2020, 1, 2), 10))
    a = worker.replay(r, outcome, {"qty": None, "timestamp": "old"}, diagnostic="replay")
    b = worker.replay(r, outcome, {"qty": None, "timestamp": "old"}, diagnostic="replay")
    assert a == b
    assert a.normalized_provider_payload["qty"] is None
    assert a.execution_outcome is outcome


def test_payload_freeze_preserves_empty_and_malformed_evidence():
    r = req(ReadOperation.POSITION_LIST, PositionListParams("acct"))
    o = FakeReadWorker().replay(r, ProviderExecutionOutcome.SUCCEEDED, {"rows": ({"qty": "bad"},)})
    assert o.normalized_provider_payload["rows"][0]["qty"] == "bad"


def test_all_operations_have_typed_params():
    assert isinstance(req(ReadOperation.TRADING_DAYS, TradingDaysParams("US", date(2026,1,1), date(2026,1,2))).params, TradingDaysParams)
    assert isinstance(req(ReadOperation.ACCOUNT_LIST, AccountListParams()).params, AccountListParams)


def test_no_provider_sdk_in_new_seam():
    import pathlib
    source = pathlib.Path("src/services/live_feed/provider_read_boundary_r1.py").read_text()
    assert "import futu" not in source.lower()
    assert "openquotecontext" not in source.lower()
    assert "opensectradecontext" not in source.lower()


def test_request_and_outcome_invariants_are_machine_enforced():
    with pytest.raises(ValueError):
        ProviderReadRequest(" ", "fake", "r1", ReadOperation.ACCOUNT_LIST, datetime.now(timezone.utc), AccountListParams())
    with pytest.raises(ValueError):
        req(ReadOperation.ACCOUNT_LIST, AccountListParams()).__class__("rt", "fake", "r1", ReadOperation.ACCOUNT_LIST, datetime(2026, 1, 1), AccountListParams())
    with pytest.raises(ValueError):
        ProviderReadOutcome("other", "fake", 1, req(ReadOperation.ACCOUNT_LIST, AccountListParams()), ProviderExecutionOutcome.SUCCEEDED, 100, 200, datetime.now(timezone.utc))
    with pytest.raises(ValueError):
        ProviderReadOutcome("rt", "fake", 1, req(ReadOperation.ACCOUNT_LIST, AccountListParams()), ProviderExecutionOutcome.SUCCEEDED, 200, 100, datetime.now(timezone.utc))


def test_generation_invalidated_is_the_only_undispatched_none_generation():
    r = req(ReadOperation.ACCOUNT_LIST, AccountListParams())
    o = ProviderReadOutcome("rt", "fake", None, r, ProviderExecutionOutcome.CANCELLED_GENERATION_INVALIDATED, None, 0, datetime.now(timezone.utc))
    assert o.worker_generation is None
    with pytest.raises(ValueError):
        ProviderReadOutcome("rt", "fake", None, r, ProviderExecutionOutcome.CANCELLED_SHUTDOWN, None, 0, datetime.now(timezone.utc))


@pytest.mark.parametrize("operation,params,payload", [
    (ReadOperation.QUOTE_SNAPSHOT, QuoteSnapshotParams(("AAPL",)), {"timestamp": "old"}),
    (ReadOperation.HISTORY_KLINE, HistoryKlineParams("AAPL", "1d", date(2020, 1, 1), date(2020, 1, 2), 10), {"rows": ()}),
    (ReadOperation.POSITION_LIST, PositionListParams("acct"), {"rows": ({"qty": None}, {"qty": "bad"})}),
])
def test_a_i_j_k_payload_is_transport_preserved(operation, params, payload):
    o = FakeReadWorker().replay(req(operation, params), ProviderExecutionOutcome.SUCCEEDED, payload)
    assert o.normalized_provider_payload == payload


@pytest.mark.parametrize("outcome", [ProviderExecutionOutcome.PROVIDER_REJECTED, ProviderExecutionOutcome.PROVIDER_EXCEPTION,
                                      ProviderExecutionOutcome.TIMEOUT, ProviderExecutionOutcome.WORKER_EXITED,
                                      ProviderExecutionOutcome.PROTOCOL_ERROR, ProviderExecutionOutcome.CANCELLED_SHUTDOWN])
def test_b_c_d_e_f_g_errors_remain_terminal_facts(outcome):
    r = req(ReadOperation.ACCOUNT_LIST, AccountListParams())
    o = FakeReadWorker().replay(r, outcome, {"rows": ()}, error=("E", "provider"))
    assert o.execution_outcome is outcome
    assert o.normalized_provider_payload == {"rows": ()}


def test_m_same_request_replays_deterministically_and_identity_differs():
    a = req(ReadOperation.ACCOUNT_LIST, AccountListParams(), "same")
    b = req(ReadOperation.ACCOUNT_LIST, AccountListParams(), "same")
    c = req(ReadOperation.ACCOUNT_LIST, AccountListParams(), "different")
    assert a == b and a.request_id != c.request_id


def test_n_allowlist_rejects_before_fake_provider_call():
    with pytest.raises(TypeError):
        req("ORDER_BOOK", {})

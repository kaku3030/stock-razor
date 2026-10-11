"""Offline tests for the paid-history safety contract; no provider I/O."""

from datetime import datetime, timedelta, timezone

from data_provider.tickflow_history_contract import (
    BLOCKED,
    PASS,
    UNKNOWN,
    HistoryBatchRequest,
    HistoryBatchResponse,
    HistoryRow,
    PaidHistoryBudget,
    fetch_history_batch,
)


START = datetime(2026, 10, 9, 1, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 9, 2, 0, tzinfo=timezone.utc)


def request() -> HistoryBatchRequest:
    return HistoryBatchRequest(("159611.SZ", "518880.SH"), START, END)


def response(**changes) -> HistoryBatchResponse:
    rows = (
        HistoryRow("159611.SZ", START + timedelta(minutes=15), "TICKFLOW"),
        HistoryRow("518880.SH", START + timedelta(minutes=15), "TICKFLOW"),
    )
    values = {
        "request_start_time": START,
        "request_end_time": END,
        "rows": rows,
        "row_count": len(rows),
        "source": "TICKFLOW",
        "source_consistency": "CONSISTENT",
        "window_complete": True,
    }
    values.update(changes)
    return HistoryBatchResponse(**values)


def test_default_disabled_rejects_with_zero_transport_calls():
    calls = []

    def transport(_request):
        calls.append(True)
        return response()

    result = fetch_history_batch(request(), transport, budget=PaidHistoryBudget())

    assert result.status == BLOCKED
    assert result.reason == "DISABLED_DEFAULT"
    assert result.provider_requests == 0
    assert calls == []


def test_missing_budget_or_unknown_quota_rejects_with_zero_transport_calls():
    calls = []

    def transport(_request):
        calls.append(True)

    missing = fetch_history_batch(request(), transport)
    unknown_budget = fetch_history_batch(
        request(), transport,
        budget=PaidHistoryBudget(enabled=True, budget_remaining=None, quota_remaining=2),
    )
    unknown_quota = fetch_history_batch(
        request(), transport,
        budget=PaidHistoryBudget(enabled=True, budget_remaining=2, quota_remaining=None),
    )

    assert missing.status == UNKNOWN
    assert missing.reason == "BUDGET_UNKNOWN"
    assert unknown_budget.status == UNKNOWN
    assert unknown_budget.reason == "BUDGET_UNKNOWN"
    assert unknown_quota.status == UNKNOWN
    assert unknown_quota.reason == "QUOTA_UNKNOWN"
    assert calls == []


def test_exhausted_quota_rejects_with_zero_transport_calls():
    calls = []
    budget = PaidHistoryBudget(enabled=True, budget_remaining=1, quota_remaining=0)

    result = fetch_history_batch(request(), lambda _request: calls.append(True), budget=budget)

    assert result.status == BLOCKED
    assert result.reason == "QUOTA_EXHAUSTED"
    assert result.provider_requests == 0
    assert calls == []
    assert budget.budget_remaining == 1
    assert budget.quota_remaining == 0


def test_exhausted_budget_rejects_with_zero_transport_calls():
    calls = []
    budget = PaidHistoryBudget(enabled=True, budget_remaining=0, quota_remaining=1)

    result = fetch_history_batch(request(), lambda _request: calls.append(True), budget=budget)

    assert result.status == BLOCKED
    assert result.reason == "BUDGET_EXHAUSTED"
    assert result.provider_requests == 0
    assert calls == []


def test_cross_source_inconsistency_is_blocked_after_budgeted_transport():
    calls = []
    budget = PaidHistoryBudget(enabled=True, budget_remaining=2, quota_remaining=2)
    bad = response(
        rows=(
            HistoryRow("159611.SZ", START + timedelta(minutes=15), "TICKFLOW"),
            HistoryRow("518880.SH", START + timedelta(minutes=15), "EASTMONEY"),
        )
    )

    result = fetch_history_batch(
        request(),
        lambda _request: (calls.append(True) or bad),
        budget=budget,
    )

    assert result.status == BLOCKED
    assert result.reason == "CROSS_SOURCE_INCONSISTENCY"
    assert result.crosscheck.checks["source_consistency"] == BLOCKED
    assert result.provider_requests == 1
    assert calls == [True]
    assert budget.budget_remaining == 1
    assert budget.quota_remaining == 1


def test_complete_window_unknown_remains_unknown():
    budget = PaidHistoryBudget(enabled=True, budget_remaining=1, quota_remaining=1)

    result = fetch_history_batch(
        request(), lambda _request: response(window_complete=None), budget=budget
    )

    assert result.status == UNKNOWN
    assert result.reason == "WINDOW_COMPLETENESS_UNKNOWN"
    assert result.crosscheck.checks["window_completeness"] == UNKNOWN
    assert result.provider_requests == 1


def test_complete_response_passes_all_independent_checks():
    budget = PaidHistoryBudget(enabled=True, budget_remaining=1, quota_remaining=1)

    result = fetch_history_batch(request(), lambda _request: response(), budget=budget)

    assert result.status == PASS
    assert result.crosscheck.reason is None
    assert all(value == PASS for value in result.crosscheck.checks.values())
    assert result.provider_requests == 1
    assert budget.budget_remaining == 0
    assert budget.quota_remaining == 0

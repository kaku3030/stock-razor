"""Offline paid request boundary: invalid input and concurrent budget contention."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from data_provider.tickflow_history_contract import (
    BLOCKED, PASS, HistoryBatchRequest, HistoryBatchResponse, HistoryRow,
    PaidHistoryBudget, fetch_history_batch,
)

START = datetime(2026, 10, 9, 1, tzinfo=timezone.utc)
END = START + timedelta(hours=1)


def _response(request):
    return HistoryBatchResponse(
        request_start_time=request.start_time,
        request_end_time=request.end_time,
        rows=(HistoryRow("159611.SZ", START + timedelta(minutes=1), "TICKFLOW"),),
        row_count=1,
        source="TICKFLOW",
        source_consistency="CONSISTENT",
        window_complete=True,
    )


def test_invalid_request_cannot_spend_or_call_provider():
    requests = (
        (HistoryBatchRequest(("159611.SZ",), END, START), "INVALID_REQUEST_WINDOW"),
        (HistoryBatchRequest(("159611.SZ",), START.replace(tzinfo=None), END),
         "INVALID_REQUEST_WINDOW"),
        (HistoryBatchRequest(("159611.SZ",), START, END, "EASTMONEY"),
         "INVALID_REQUEST_SOURCE"),
        (HistoryBatchRequest((), START, END), "INVALID_REQUEST_SYMBOLS"),
        (HistoryBatchRequest(("159611.SZ", "159611.SZ"), START, END),
         "DUPLICATE_REQUEST_SYMBOLS"),
        (HistoryBatchRequest(("159611.SZ ",), START, END),
         "INVALID_REQUEST_SYMBOLS"),
        (HistoryBatchRequest(tuple(f"{idx:06d}.SZ" for idx in range(201)), START, END),
         "REQUEST_SYMBOL_CAP_EXCEEDED"),
    )
    for request, reason in requests:
        calls = []
        budget = PaidHistoryBudget(enabled=True, budget_remaining=2, quota_remaining=2)
        result = fetch_history_batch(
            request, lambda req: (calls.append(req) or _response(req)), budget=budget
        )
        assert result.status == BLOCKED
        assert result.reason == reason
        assert result.provider_requests == 0
        assert not calls
        assert (budget.budget_remaining, budget.quota_remaining) == (2, 2)


def test_parallel_callers_cannot_overdraw_one_shared_budget():
    request = HistoryBatchRequest(("159611.SZ",), START, END)
    budget = PaidHistoryBudget(enabled=True, budget_remaining=3, quota_remaining=3)

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(
            lambda _: fetch_history_batch(request, _response, budget=budget),
            range(64),
        ))
    assert sum(result.status == PASS for result in results) == 3
    assert sum(result.provider_requests for result in results) == 3
    assert (budget.budget_remaining, budget.quota_remaining) == (0, 0)

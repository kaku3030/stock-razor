"""No provider I/O; exercise one-file SQLite atomic quota reservations."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from data_provider.tickflow_request_ledger import (
    initialize_offline_ledger, reserve_local_request,
)


def test_missing_or_disabled_ledger_refuses_requests(tmp_path):
    path = tmp_path / "unused.db"
    assert reserve_local_request(path, request_id="probe").status == "UNKNOWN"
    initialize_offline_ledger(path, request_units=10, quota_units=10)
    result = reserve_local_request(path, request_id="probe")
    assert result.status == "BLOCKED"
    assert result.reason == "LEDGER_DISABLED"
    assert result.paid_transport_calls == 0


def test_parallel_callers_with_same_file_cannot_overdraw(tmp_path):
    path = tmp_path / "budget.db"
    initialize_offline_ledger(path, request_units=3, quota_units=3, enabled=True)
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(
            lambda i: reserve_local_request(path, request_id=f"req-{i}"),
            range(35),
        ))
    assert sum(r.status == "RESERVED_LOCAL_ONLY" for r in results) == 3
    assert sum(r.reserved_units for r in results) == 3
    assert all(r.paid_transport_calls == 0 for r in results)
    assert all(r.radar_admission == "BLOCKED" for r in results)
    assert not any(r.paper_auto_ready for r in results)


def test_duplicate_request_id_is_never_reserved_twice(tmp_path):
    path = tmp_path / "budget.db"
    initialize_offline_ledger(path, request_units=2, quota_units=2, enabled=True)
    assert reserve_local_request(path, request_id="job.1").reserved_units == 1
    duplicate = reserve_local_request(path, request_id="job.1")
    assert duplicate.status == "BLOCKED"
    assert duplicate.reason == "REQUEST_ALREADY_RESERVED"
    assert reserve_local_request(path, request_id="job.2").reserved_units == 1
    assert reserve_local_request(path, request_id="job.3").status == "BLOCKED"


def test_cannot_reset_existing_budget_or_use_invalid_units(tmp_path):
    path = tmp_path / "budget.db"
    initialize_offline_ledger(path, request_units=1, quota_units=1, enabled=True)
    with pytest.raises(FileExistsError):
        initialize_offline_ledger(path, request_units=10, quota_units=10)
    for count in (0, -1, True, 1.5):
        assert reserve_local_request(
            path, request_id="bad-unit", units=count
        ).status == "BLOCKED"
    assert reserve_local_request(path, request_id="bad id").status == "BLOCKED"

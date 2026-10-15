import pytest
from datetime import datetime, timezone
from engineering_autonomy import feedback_hub as hub_module

from engineering_autonomy.feedback_hub import FeedbackHub, FeedbackHubError


def test_submit_is_idempotent_and_preflight_is_structured(tmp_path):
    hub = FeedbackHub(tmp_path / "feedback.sqlite3")
    first = hub.submit(source="US_RADAR", priority="P1", title="gap", details="closed bar gap",
                       evidence={"sha": "abc"}, source_ref="radar:us:1")
    second = hub.submit(source="US_RADAR", priority="P1", title="gap", details="different text",
                        evidence={"sha": "def"}, source_ref="radar:us:1")
    assert first.id == second.id
    assert hub.preflight()["open_p1"] == 1
    assert len(hub.audit(first.id)) == 1
    hub.close()


def test_claim_is_atomic_and_writeback_requires_owner(tmp_path):
    hub = FeedbackHub(tmp_path / "feedback.sqlite3")
    item = hub.submit(source="CN_WINDOW", priority="P0", title="handoff", details="main must inspect",
                      evidence={"run": 7}, source_ref="window:cn:7")
    claimed = hub.claim(worker_id="main:7")
    assert claimed and claimed.id == item.id and claimed.status == "CLAIMED"
    try:
        hub.writeback(feedback_id=item.id, worker_id="other", status="DONE", evidence={})
    except FeedbackHubError:
        pass
    else:
        raise AssertionError("foreign worker must not write back")
    done = hub.writeback(feedback_id=item.id, worker_id="main:7", status="DONE", evidence={"ci": "run/7"})
    assert done.status == "DONE"
    assert hub.preflight()["open"] == 0
    hub.close()


def test_corrupt_database_fails_closed(tmp_path):
    path = tmp_path / "feedback.sqlite3"
    path.write_text("not sqlite", encoding="utf-8")
    try:
        FeedbackHub(path)
    except FeedbackHubError:
        pass
    else:
        raise AssertionError("corrupt feedback store must fail closed")


def test_failed_writeback_requeues_until_attempt_budget(tmp_path):
    hub = FeedbackHub(tmp_path / "feedback.sqlite3")
    item = hub.submit(source="CN_RADAR", priority="P1", title="retry", details="retry me",
                      evidence={}, source_ref="radar:cn:retry", max_attempts=2)
    claimed = hub.claim(worker_id="main:retry")
    assert claimed and claimed.attempts == 1
    retried = hub.writeback(feedback_id=item.id, worker_id="main:retry", status="FAILED", evidence={}, error="timeout")
    assert retried.status == "NEW"
    claimed_again = hub.claim(worker_id="main:retry-2")
    assert claimed_again and claimed_again.attempts == 2
    blocked = hub.writeback(feedback_id=item.id, worker_id="main:retry-2", status="FAILED", evidence={}, error="timeout")
    assert blocked.status == "BLOCKED"
    hub.close()


def test_claim_does_not_duplicate_across_workers(tmp_path):
    path = tmp_path / "feedback.sqlite3"
    hub = FeedbackHub(path)
    item = hub.submit(source="US_WINDOW", priority="P1", title="one", details="one",
                      evidence={}, source_ref="window:us:1")
    hub.close()

    def worker(worker_id):
        local = FeedbackHub(path)
        claimed = local.claim(worker_id=worker_id)
        local.close()
        return claimed.id if claimed else None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(worker, ["worker-a", "worker-b"]))
    assert claimed.count(item.id) == 1
    assert claimed.count(None) == 1


@pytest.mark.parametrize("first_status", ("DONE", "BLOCKED", "FAILED"))
def test_writeback_rejects_terminal_or_requeued_item(tmp_path, first_status):
    hub = FeedbackHub(tmp_path / "feedback.sqlite3")
    item = hub.submit(
        source="US_RADAR", priority="P0", title="terminal", details="guard state",
        evidence={}, source_ref=f"us:terminal:{first_status.lower()}",
    )
    assert hub.claim(worker_id="main:one") is not None
    result = hub.writeback(
        feedback_id=item.id, worker_id="main:one", status=first_status,
        evidence={}, error="safe error" if first_status == "FAILED" else None,
    )
    audit_before = hub.audit(item.id)
    with pytest.raises(FeedbackHubError, match="no longer active"):
        hub.writeback(
            feedback_id=item.id, worker_id="main:one", status="IN_PROGRESS",
            evidence={"status": "UNKNOWN"},
        )
    assert hub.audit(item.id) == audit_before
    current = hub._connection.execute(
        "SELECT status FROM feedback WHERE id=?", (item.id,),
    ).fetchone()
    assert current["status"] == result.status
    hub.close()


def test_writeback_rejects_expired_claim_even_without_new_owner(tmp_path):
    hub = FeedbackHub(tmp_path / "feedback.sqlite3")
    item = hub.submit(
        source="CN_WINDOW", priority="P1", title="expired", details="lease check",
        evidence={}, source_ref="cn:expired:lease",
    )
    assert hub.claim(worker_id="main:leased") is not None
    hub._connection.execute(
        "UPDATE feedback SET lease_until=? WHERE id=?",
        ("2000-01-01T00:00:00Z", item.id),
    )
    audit_before = hub.audit(item.id)
    with pytest.raises(FeedbackHubError, match="lease expired"):
        hub.writeback(
            feedback_id=item.id, worker_id="main:leased",
            status="DONE", evidence={"ci": "fake"},
        )
    assert hub.audit(item.id) == audit_before
    reclaimed = hub.claim(worker_id="main:new")
    assert reclaimed is not None
    assert reclaimed.attempts == 2
    assert hub.writeback(
        feedback_id=item.id, worker_id="main:new", status="DONE", evidence={},
    ).status == "DONE"
    hub.close()


def test_legacy_second_precision_lease_expires_within_same_second(tmp_path, monkeypatch):
    # Previously lexical "09:20:00Z" > "09:20:00.500000Z" incorrectly
    # treated a lease that expired 500ms ago as live.
    frozen = datetime(2026, 10, 16, 9, 20, 0, 500000, tzinfo=timezone.utc)
    monkeypatch.setattr(hub_module, "_now", lambda: frozen)
    hub = FeedbackHub(tmp_path / "feedback.sqlite3")
    item = hub.submit(
        source="CN_RADAR", priority="P0", title="legacy lease",
        details="seconds precision", evidence={}, source_ref="cn:lease:legacy",
    )
    assert hub.claim(worker_id="old-owner") is not None
    hub._connection.execute(
        "UPDATE feedback SET lease_until=? WHERE id=?",
        ("2026-10-16T09:20:00Z", item.id),
    )
    audit_before = hub.audit(item.id)
    with pytest.raises(FeedbackHubError, match="lease expired"):
        hub.writeback(
            feedback_id=item.id, worker_id="old-owner", status="DONE",
            evidence={},
        )
    assert hub.audit(item.id) == audit_before
    fresh = hub.claim(worker_id="new-owner")
    assert fresh is not None and fresh.id == item.id
    assert fresh.attempts == 2
    assert hub.writeback(
        feedback_id=item.id, worker_id="new-owner",
        status="DONE", evidence={},
    ).status == "DONE"
    hub.close()


def test_corrupt_existing_lease_timestamp_never_grants_writeback(tmp_path):
    hub = FeedbackHub(tmp_path / "feedback.sqlite3")
    item = hub.submit(
        source="US_WINDOW", priority="P1", title="invalid lease",
        details="bad timestamp", evidence={}, source_ref="us:lease:invalid",
    )
    assert hub.claim(worker_id="old-owner") is not None
    hub._connection.execute(
        "UPDATE feedback SET lease_until=? WHERE id=?",
        ("not-a-valid-time", item.id),
    )
    with pytest.raises(FeedbackHubError, match="lease expired"):
        hub.writeback(
            feedback_id=item.id, worker_id="old-owner",
            status="DONE", evidence={},
        )
    assert hub.claim(worker_id="different-owner") is None
    hub.close()


@pytest.mark.parametrize("bad_evidence", (
    {"api_key": "not-a-real-key"},
    {"checks": {"authorization": "Bearer fake"}},
    {"checks": [{"status": "PASS"}, {"password": "fake"}]},
    {"status": "Authorization: Bearer not-a-real-token"},
    {"status": "AKIAFAKEFAKEFAKEFAKE"},
    {"account_id": "123456789012"},
    {"raw_price": 123.45},
    {"status": "123456789012"},
    {"unreviewed_custom_field": "PASS"},
    {"status": "raw close 123.45"},
    {"status": 123.45},
    {"run": "7"},
    {"latency_ms": -1},
    {"closed": "true"},
    {"checks": [{"checks": [{"checks": [{"checks": [
        {"status": "TOO_DEEP"},
    ]}]}]}]},
))
def test_submit_rejects_sensitive_or_unreviewed_evidence_without_audit(
    tmp_path, bad_evidence,
):
    hub = FeedbackHub(tmp_path / "feedback.sqlite3")
    with pytest.raises(FeedbackHubError):
        hub.submit(
            source="US_WINDOW", priority="P0", title="safe title",
            details="safe details", source_ref="us:safe:1",
            evidence=bad_evidence,
        )
    assert hub.preflight()["open"] == 0
    assert hub._connection.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0
    hub.close()


def test_evidence_allowlist_preserves_safe_nested_operational_facts(tmp_path):
    hub = FeedbackHub(tmp_path / "feedback.sqlite3")
    item = hub.submit(
        source="CN_RADAR", priority="P0", title="data provenance",
        details="source mismatch", source_ref="cn:probe:1",
        evidence={
            "sha": "abc", "run": 7, "status": "BLOCKED",
            "closed": False, "latency_ms": 1.23,
            "checks": [{"status": "PASS"}, {"reason": "NO_DATA"}],
        },
    )
    assert item.evidence["checks"][1]["reason"] == "NO_DATA"
    assert hub.claim(worker_id="main:1") is not None
    result = hub.writeback(
        feedback_id=item.id, worker_id="main:1", status="DONE",
        evidence={"ci": "run/7", "status": "PASS"},
    )
    assert result.status == "DONE"
    assert len(hub.audit(item.id)) == 2
    hub.close()


@pytest.mark.parametrize("text_field", ("title", "details", "error"))
def test_sensitive_free_text_never_reaches_feedback_store(tmp_path, text_field):
    hub = FeedbackHub(tmp_path / "feedback.sqlite3")
    params = {
        "source": "US_RADAR", "priority": "P1", "title": "safe",
        "details": "safe", "source_ref": "us:run:3", "evidence": {},
    }
    suspect = "Authorization: Bearer not-a-real-token"
    if text_field != "error":
        params[text_field] = suspect
        with pytest.raises(FeedbackHubError):
            hub.submit(**params)
        assert hub.preflight()["open"] == 0
    else:
        item = hub.submit(**params)
        assert hub.claim(worker_id="main:2") is not None
        audits = hub.audit(item.id)
        with pytest.raises(FeedbackHubError):
            hub.writeback(
                feedback_id=item.id, worker_id="main:2",
                status="FAILED", evidence={}, error=suspect,
            )
        assert hub.audit(item.id) == audits
    hub.close()

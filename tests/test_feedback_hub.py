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

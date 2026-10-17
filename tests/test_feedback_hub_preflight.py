import pytest

from engineering_autonomy.feedback_hub import FeedbackHub, FeedbackHubError
from engineering_autonomy.loop import run_queue


def test_run_queue_requires_explicit_feedback_path(tmp_path):
    with pytest.raises(FeedbackHubError, match="persistent feedback_path is required"):
        run_queue(
            queue_path=tmp_path / "queue.json",
            state_path=tmp_path / "state.json",
            feedback_path=None,
        )


def test_run_queue_rejects_missing_feedback_store_without_creating_it(tmp_path):
    absent = tmp_path / "cloud-mounted" / "feedback.sqlite3"
    with pytest.raises(FeedbackHubError, match="existing feedback hub"):
        run_queue(
            queue_path=tmp_path / "queue.json",
            state_path=tmp_path / "state.json",
            feedback_path=absent,
        )
    assert not absent.exists()
    assert not absent.parent.exists()
    assert not (tmp_path / "state.json").exists()


def test_existing_but_corrupt_store_cannot_qualify(tmp_path):
    path = tmp_path / "feedback.sqlite3"
    path.write_text("not a real sqlite database", encoding="utf-8")
    with pytest.raises(FeedbackHubError):
        FeedbackHub(path, require_existing=True)
    assert path.read_text(encoding="utf-8") == "not a real sqlite database"


def test_preflight_existing_store_is_read_only_and_durable(tmp_path):
    path = tmp_path / "feedback.sqlite3"
    writer = FeedbackHub(path)
    item = writer.submit(
        source="CN_RADAR", priority="P0", title="source audit",
        details="needs readback", evidence={"status": "BLOCKED"},
        source_ref="cn:readback:1",
    )
    writer.close()
    before = path.read_bytes()
    reader = FeedbackHub(path, require_existing=True)
    assert reader.preflight()["open_p0"] == 1
    assert reader.audit(item.id)[0]["event_type"] == "SUBMITTED"
    reader.close()
    assert path.read_bytes() == before


@pytest.mark.parametrize("table", ["feedback", "audit"])
def test_existing_table_names_without_required_columns_cannot_qualify(tmp_path, table):
    import sqlite3

    path = tmp_path / "feedback.sqlite3"
    writer = FeedbackHub(path)
    writer.close()
    with sqlite3.connect(path) as database:
        database.execute(f"DROP TABLE {table}")
        database.execute(f"CREATE TABLE {table} (placeholder TEXT)")
    before = path.read_bytes()
    with pytest.raises(FeedbackHubError, match="schema"):
        FeedbackHub(path, require_existing=True)
    assert path.read_bytes() == before


def test_monitor_reports_expired_claim_without_mutation_or_liveness_promotion(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from engineering_autonomy import feedback_hub as hub_module

    now = datetime(2026, 10, 17, 5, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(hub_module, "_now", lambda: now)
    path = tmp_path / "feedback.sqlite3"
    writer = FeedbackHub(path)
    item = writer.submit(source="US_RADAR", priority="P0", title="stalled source",
                         details="requires recovery", evidence={}, source_ref="us:monitor:1")
    writer.claim(worker_id="worker:1", lease_seconds=30)
    writer.close()
    monkeypatch.setattr(hub_module, "_now", lambda: now + timedelta(seconds=31))
    before = path.read_bytes()
    reader = FeedbackHub(path, require_existing=True)
    report = reader.preflight()
    assert report["status"] == "READY"
    assert report["expired_claims"] == 1
    assert report["lease_health"] == "EXPIRED"
    assert report["worker_liveness"] == "NOT_VERIFIED"
    assert [event["event_type"] for event in reader.audit(item.id)] == ["SUBMITTED", "CLAIMED"]
    reader.close()
    assert path.read_bytes() == before


@pytest.mark.parametrize("lease", ["invalid", "2026-10-17T05:00:00", None])
def test_monitor_keeps_invalid_claim_evidence_visible(tmp_path, lease):
    import sqlite3

    path = tmp_path / "feedback.sqlite3"
    writer = FeedbackHub(path)
    writer.submit(source="CN_RADAR", priority="P1", title="claim audit",
                  details="lease evidence", evidence={}, source_ref="cn:monitor:1")
    writer.claim(worker_id="worker:1")
    writer.close()
    with sqlite3.connect(path) as database:
        database.execute("UPDATE feedback SET lease_until=?", (lease,))
    reader = FeedbackHub(path, require_existing=True)
    report = reader.preflight()
    assert report["invalid_claims"] == 1
    assert report["lease_health"] == "INVALID"
    assert report["worker_liveness"] == "NOT_VERIFIED"
    reader.close()


@pytest.mark.parametrize("claimed", [False, True])
def test_monitor_never_promotes_idle_or_unexpired_claim_to_worker_liveness(tmp_path, claimed):
    path = tmp_path / "feedback.sqlite3"
    writer = FeedbackHub(path)
    if claimed:
        writer.submit(source="US_RADAR", priority="P1", title="lease presence",
                      details="not a process heartbeat", evidence={}, source_ref="us:monitor:live")
        writer.claim(worker_id="worker:1", lease_seconds=3600)
    writer.close()
    reader = FeedbackHub(path, require_existing=True)
    report = reader.preflight()
    assert report["active_claims"] == int(claimed)
    assert report["expired_claims"] == report["invalid_claims"] == 0
    assert report["lease_health"] == (
        "UNEXPIRED_NOT_LIVENESS_PROOF" if claimed else "NO_ACTIVE_CLAIMS"
    )
    assert report["worker_liveness"] == "NOT_VERIFIED"
    reader.close()

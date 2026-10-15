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

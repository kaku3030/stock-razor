import pytest

from engineering_autonomy.feedback_hub import FeedbackHubError
from engineering_autonomy.loop import run_queue


def test_run_queue_requires_explicit_feedback_path(tmp_path):
    with pytest.raises(FeedbackHubError, match="persistent feedback_path is required"):
        run_queue(
            queue_path=tmp_path / "queue.json",
            state_path=tmp_path / "state.json",
            feedback_path=None,
        )

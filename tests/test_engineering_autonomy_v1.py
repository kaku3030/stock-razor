from scripts.engineering_autonomy_v1 import evaluate_candidate


def metadata(**overrides):
    value = {
        "base_repo": "kaku3030/stock-razor",
        "head_repo": "kaku3030/stock-razor",
        "draft": False,
        "body": "AUTONOMY_CANDIDATE=LOW_RISK",
        "head_sha": "a" * 40,
    }
    value.update(overrides)
    return value


def test_low_risk_candidate_is_eligible_for_same_repo_safe_paths():
    result = evaluate_candidate(
        metadata=metadata(),
        changed_files=["tests/test_engineering_autonomy_v1.py", "docs/example.md"],
    )

    assert result["decision"] == "AUTO_MERGE"
    assert result["eligible"] is True
    assert result["reasons"] == []


def test_policy_is_fail_closed_for_fork_draft_missing_marker_and_runtime_code():
    result = evaluate_candidate(
        metadata=metadata(
            head_repo="someone/stock-razor",
            draft=True,
            body="ordinary PR",
        ),
        changed_files=["src/production.py"],
    )

    assert result["decision"] == "OBSERVE_ONLY"
    assert result["eligible"] is False
    assert result["reasons"] == [
        "HEAD_REPOSITORY_MISMATCH",
        "DRAFT_PR",
        "MISSING_LOW_RISK_MARKER",
        "DISALLOWED_PATHS",
    ]


def test_workflow_file_is_the_only_allowed_github_workflow_path():
    allowed = evaluate_candidate(
        metadata=metadata(),
        changed_files=[".github/workflows/engineering-autonomy-v1.yml"],
    )
    blocked = evaluate_candidate(
        metadata=metadata(),
        changed_files=[".github/workflows/deploy-cn-tickflow-research.yml"],
    )

    assert allowed["eligible"] is True
    assert blocked["eligible"] is False

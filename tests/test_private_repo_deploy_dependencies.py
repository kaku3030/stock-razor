"""Deterministic private GitHub migration audit without external IO."""

from pathlib import Path

from scripts.audit_private_repo_deploy_dependencies import (
    PublicRepoDependency,
    build_static_private_migration_report,
    scan_private_repo_blockers,
)


def test_detects_raw_and_clone_public_dependencies_without_leaking_urls(tmp_path):
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / "ops/aws").mkdir(parents=True)
    (tmp_path / ".github/workflows/deploy.yml").write_text(
        'curl -fsSL https://raw.githubusercontent.com/kaku3030/stock-razor/$SHA/install.sh\n'
        'echo token-secret-do-not-print\n', encoding="utf-8"
    )
    (tmp_path / "ops/aws/install.sh").write_text(
        'git clone https://github.com/kaku3030/stock-razor.git repo\n',
        encoding="utf-8"
    )
    got = scan_private_repo_blockers(tmp_path)
    assert {(v.file, v.line, v.kind) for v in got} == {
        (".github/workflows/deploy.yml", 1, "PUBLIC_RAW_GITHUB"),
        ("ops/aws/install.sh", 1, "UNAUTHENTICATED_GITHUB_CLONE"),
    }
    assert "token-secret-do-not-print" not in str(got)
    assert "https://" not in str(got)


def test_fully_private_artifact_delivery_has_no_public_git_blockers(tmp_path):
    (tmp_path / "ops/aws").mkdir(parents=True)
    (tmp_path / "ops/aws/install.sh").write_text(
        'test -n "$REPO_REF" && aws s3 cp "$OBJECT_URI" /tmp/source.tar.gz\n',
        encoding="utf-8"
    )
    assert scan_private_repo_blockers(tmp_path) == []


def test_current_repo_report_has_only_allowlisted_file_metadata():
    # Remains valid after future migration removes all public dependencies.
    root = Path(__file__).resolve().parents[1]
    hits = scan_private_repo_blockers(root)
    assert all(
        entry.file.startswith((".github/workflows/", "ops/aws/"))
        and entry.line > 0
        and entry.kind in {"PUBLIC_RAW_GITHUB", "UNAUTHENTICATED_GITHUB_CLONE"}
        for entry in hits
    )


def test_zero_static_hits_does_not_grant_private_visibility():
    # The former code reported private_migration_ready=True here even when
    # authenticated cloud delivery, recovery and approval were unproven.
    report = build_static_private_migration_report([])
    assert report["static_public_source_dependencies_cleared"] is True
    assert report["public_fetch_dependency_count"] == 0
    assert report["private_migration_ready"] is False
    assert report["repository_visibility_change_authorized"] is False
    assert report["authenticated_source_delivery_verified"] is False
    assert report["aws_restart_recovery_rollback_verified"] is False
    assert report["user_visibility_approval_verified"] is False
    assert report["aws_changes_performed"] is False
    assert report["trading_gates_unchanged"] is True


def test_static_blockers_remain_fail_closed_and_sanitized():
    item = PublicRepoDependency(
        file="ops/aws/install.sh", line=4, kind="UNAUTHENTICATED_GITHUB_CLONE"
    )
    report = build_static_private_migration_report([item])
    assert report["static_public_source_dependencies_cleared"] is False
    assert report["public_fetch_dependency_count"] == 1
    assert report["blockers"] == [{"file": item.file, "line": 4, "kind": item.kind}]
    assert report["private_migration_ready"] is False
    assert report["repository_visibility_change_authorized"] is False
    assert "https://" not in str(report)

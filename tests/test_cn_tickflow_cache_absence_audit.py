"""Audit missing TickFlow cache without leaking file or provider details."""
from pathlib import Path

import pytest

import scripts.audit_cn_tickflow_research_runtime as audit


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (None, "FILE_MISSING"),
        ("", "FILE_SIZE_INVALID"),
        ("not-json", "JSON_INVALID"),
        ("{}", "SCHEMA_INVALID"),
    ],
)
def test_missing_cache_fails_closed_with_sanitized_reason(
    tmp_path: Path, monkeypatch, content, expected,
):
    cache = tmp_path / "latest-research-observation.json"
    if content is not None:
        cache.write_text(content, encoding="utf-8")
    monkeypatch.setattr(audit, "WORKER_FILE", cache)
    monkeypatch.setattr(audit, "active", lambda _unit: True)

    result = audit.sample()
    assert result["status"] == "NO_VALID_CACHE"
    assert result["cache_unavailable_reason"] == expected
    assert result["repo_sha_match"] is False
    assert result["sequence"] is None
    assert result["all_four_historical_requests_ok"] is False
    assert result["all_four_readonly_requests_ok"] is False
    assert result["mcp_cache_consumer"] == "NOT_VERIFIED"


def test_oversized_private_cache_never_read_or_exported(tmp_path, monkeypatch):
    cache = tmp_path / "latest-research-observation.json"
    cache.write_bytes(b"Z" * (audit.MAX_FILE_BYTES + 1))
    monkeypatch.setattr(audit, "WORKER_FILE", cache)
    monkeypatch.setattr(audit, "active", lambda _unit: True)
    result = audit.sample()
    assert result["status"] == "NO_VALID_CACHE"
    assert result["cache_unavailable_reason"] == "FILE_SIZE_INVALID"
    # An isolated character can appear in safe enum names (e.g. SIZE).
    # Only the full unique raw fixture payload must remain undisclosed.
    assert "Z" * 64 not in str(result)


def test_public_workflow_requires_fixed_failure_enum_and_serialized_deploy():
    root = Path(__file__).resolve().parents[1]
    source = (
        root / ".github/workflows/audit-cn-tickflow-live-research.yml"
    ).read_text(encoding="utf-8")
    assert 'keys=("status","cache_unavailable_reason",' in source
    assert 'assert d[when].get("cache_unavailable_reason") in cache_absence' in source
    assert 'group: cn-tickflow-research-worker' in source
    assert "cancel-in-progress: false" in source
    assert "RADAR_ADMISSION=BLOCKED" in source
    assert "LIVE_TRADE=NO" in source


def test_aws_audit_accepts_same_bounded_size_as_private_writer_and_reader():
    from data_provider.cn_tickflow_research_cache import MAX_BYTES

    # Auditor used to impose a smaller 150 KB limit and falsely report
    # NO_VALID_CACHE for a legitimate 150-350 KB private snapshot.
    assert audit.MAX_FILE_BYTES == MAX_BYTES == 350_000


@pytest.mark.parametrize("symbol_index", [0, 1])
@pytest.mark.parametrize("period", ["15M", "60M", "5M", "1D"])
@pytest.mark.parametrize("action", ["FETCH", "NORMALIZE"])
def test_worker_all_requested_failure_stages_are_safely_classified(
    symbol_index, period, action,
):
    # AWS worker include_supplemental=True requests all four timeframes;
    # 5m/1d outages must not disappear into UNKNOWN in the public audit.
    stage = f"S{symbol_index}_{period}_{action}"
    assert audit.safe_failure_stage(stage) == stage


@pytest.mark.parametrize("malicious", [
    None, 0, True, {}, "S0_1M_FETCH", "S2_5M_FETCH",
    "S0_5M_FETCH\\nAPI_KEY=DO_NOT_ECHO", "S1_1D_NORMALIZE_SECRET",
])
def test_worker_failure_stage_projection_is_enum_only(malicious):
    assert audit.safe_failure_stage(malicious) == "UNKNOWN"
    assert "DO_NOT_ECHO" not in audit.safe_failure_stage(malicious)


@pytest.mark.parametrize(("record", "expected"), [
    ("TICKFLOW_RESEARCH_BOOT=BLOCKED:RuntimeError", "BOOT_BLOCKED"),
    ("TICKFLOW_RESEARCH_POLL=BLOCKED:RateLimitError", "POLL_BLOCKED"),
    ("TICKFLOW_RESEARCH_POLL=RESEARCH_ONLY_PASS", "POLL_RESEARCH_ONLY_PASS"),
    ("provider_error=API_KEY_SECRET_SHOULD_NEVER_LEAVE", "NO_RECENT_LIFECYCLE_MARKER"),
])
def test_worker_journal_evidence_never_exports_raw_log(monkeypatch, record, expected):
    import subprocess
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(
            argv, 0, stdout="private_api_key=KEEP_PRIVATE\n" + record,
            stderr="confidential provider stack",
        )

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    state = audit.safe_worker_journal_observation()
    assert state == expected
    assert "KEEP_PRIVATE" not in state
    assert "confidential" not in state
    assert calls[0][0][0] == "journalctl"
    assert calls[0][1]["timeout"] == 5
    assert calls[0][1]["capture_output"] is True


def test_worker_journal_unavailable_fails_closed(monkeypatch):
    import subprocess

    monkeypatch.setattr(
        audit.subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, stdout="", stderr="SECRET"),
    )
    assert audit.safe_worker_journal_observation() == "JOURNAL_UNAVAILABLE"


def test_public_tickflow_workflow_restricts_journal_projection_to_enums():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/audit-cn-tickflow-live-research.yml").read_text()
    assert '"worker_journal_observation"' in workflow
    assert 'assert d[when].get("worker_journal_observation") in worker_journal' in workflow
    assert '"BOOT_BLOCKED","POLL_BLOCKED","POLL_RESEARCH_ONLY_PASS"' in workflow
    assert "StandardErrorContent" not in workflow


def test_writer_preflights_reader_byte_bound_and_preserves_existing_cache(tmp_path):
    from data_provider.cn_tickflow_research_cache import atomic_publish, MAX_BYTES

    path = tmp_path / "private-cache.json"
    atomic_publish(str(path), {"status": "BLOCKED", "source": "research"})
    original = path.read_bytes()
    oversized = {"secret_in_private_payload": "V" * MAX_BYTES}
    with pytest.raises(ValueError, match="bounded bytes"):
        atomic_publish(str(path), oversized)
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
    assert "V" * 64 not in path.read_text(encoding="utf-8")


def test_private_tickflow_writer_enforces_same_limit_as_audit_and_reader():
    from data_provider.cn_tickflow_research_cache import atomic_publish, MAX_BYTES
    import inspect

    source = inspect.getsource(atomic_publish)
    assert audit.MAX_FILE_BYTES == MAX_BYTES == 350_000
    assert 'len(encoded.encode("utf-8"))>MAX_BYTES' in source
    assert source.index("len(encoded.encode") < source.index("parent.mkdir")

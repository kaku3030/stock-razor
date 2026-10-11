from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

from scripts.probe_us_cloud_exact import probe


def test_workflow_delivers_pinned_compressed_source_without_public_raw_or_leaky_logs():
    workflow = Path(".github/workflows/probe-us-cloud-exact.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "ref: ${{ github.sha }}" in workflow
    assert 'test "$revision" = "${{ github.sha }}"' in workflow
    assert "gzip -n -9 -c scripts/probe_us_cloud_exact.py | base64 -w0" in workflow
    assert "sha256sum -c - >/dev/null" in workflow
    assert "US_EXACT_CLOUD_PROBE_SSM_PAYLOAD_TOO_LARGE" in workflow
    assert "US_EXACT_CLOUD_PROBE_INVALID_DURATION" in workflow
    assert "US_EXACT_CLOUD_PROBE_INVALID_SYMBOLS" in workflow
    assert "read -r -d '' remote <<REMOTE || true" in workflow
    assert "          set -eu\n          umask 077" in workflow
    assert "raw.githubusercontent.com" not in workflow
    assert "curl -fsSL" not in workflow
    assert "git clone" not in workflow
    assert "StandardErrorContent" not in workflow
    assert "tail -n 12" not in workflow
    assert "print(json.dumps(x, sort_keys=True))" not in workflow
    assert "US_EXACT_CLOUD_PROBE_SANITIZED=" in workflow
    assert 'x.get("live_trade") == "NO"' in workflow
    assert 'x.get("radar_admission") == "BLOCKED"' in workflow
    assert 'x.get("source_arbiter_admission") == "BLOCKED"' in workflow
    assert "systemctl restart" not in workflow
    assert "LIVE_TRADE=NO" in workflow


def test_real_ssm_remote_template_reconstructs_and_verifies_compressed_source():
    """Re-run the exact POSIX remote template locally, including tamper denial."""
    import base64
    import gzip
    from hashlib import sha256

    import pytest

    if not all(shutil.which(c) for c in ("sh", "gzip", "sha256sum", "base64", "python3")):
        pytest.skip("POSIX sh and source decoding tools required")
    workflow = Path(".github/workflows/probe-us-cloud-exact.yml").read_text(encoding="utf-8")
    fixture = b'print("SOURCE_COMPRESSED_SSM_ROUNDTRIP=PASS")\n'
    digest = sha256(fixture).hexdigest()
    packed = base64.b64encode(gzip.compress(fixture, mtime=0)).decode("ascii")
    fragment = workflow.split("read -r -d '' remote <<REMOTE || true\n", 1)[1].split(
        "\n          REMOTE", 1
    )[0]
    remote = "\n".join(
        line[10:] if line.startswith("          ") else line
        for line in fragment.splitlines()
    )
    remote = remote.replace("$packed", packed).replace("$probe_hash", digest)
    remote = remote.replace("$revision", "a" * 40)
    remote = remote.replace("$DURATION_SECONDS", "30")
    remote = remote.replace("$SYMBOLS", "US.AMD")
    remote = remote.replace("\\$", "$")
    result = subprocess.run(
        ["sh", "-c", remote], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert "SOURCE_COMPRESSED_SSM_ROUNDTRIP=PASS" in result.stdout
    tampered = subprocess.run(
        ["sh", "-c", remote.replace(digest, "0" * 64)],
        capture_output=True, text=True, timeout=10,
    )
    assert tampered.returncode != 0
    assert "SOURCE_COMPRESSED_SSM_ROUNDTRIP=PASS" not in tampered.stdout


def test_private_source_scanner_excludes_migrated_us_probe():
    from scripts.audit_private_repo_deploy_dependencies import scan_private_repo_blockers

    hits = scan_private_repo_blockers(Path(__file__).resolve().parents[1])
    assert all(hit.file != ".github/workflows/probe-us-cloud-exact.yml" for hit in hits)


def test_probe_requires_exact_sha_and_keeps_unobservable_latency_blocked(monkeypatch):
    payloads = [
        {
            "repo_sha": "a" * 40,
            "sequence": 1,
            "event_count": 1,
            "last_push_utc": "2026-10-09T00:00:00+00:00",
            "emitted_at_utc": "2026-10-09T00:00:00+00:00",
            "latest_k1m_time_keys": {x: "2026-10-09 09:30:00" for x in ("US.AMD", "US.NVDA", "US.TSLA", "US.QQQ")},
            "k1m_currentness": {x: {"status": "PASS", "age_seconds": 1} for x in ("US.AMD", "US.NVDA", "US.TSLA", "US.QQQ")},
            "canonical_cache": {x: {"bar_count_15m": 2, "bar_count_1h": 1} for x in ("US.AMD", "US.NVDA", "US.TSLA", "US.QQQ")},
            "cache_session_us": "US_RTH",
            "bar_closure": "UNPROVEN",
            "adapter_diagnostics": {},
        },
        {
            "repo_sha": "a" * 40,
            "sequence": 2,
            "event_count": 2,
            "last_push_utc": "2026-10-09T00:00:02+00:00",
            "emitted_at_utc": "2026-10-09T00:00:02+00:00",
            "latest_k1m_time_keys": {x: "2026-10-09 09:31:00" for x in ("US.AMD", "US.NVDA", "US.TSLA", "US.QQQ")},
            "k1m_currentness": {x: {"status": "PASS", "age_seconds": 1} for x in ("US.AMD", "US.NVDA", "US.TSLA", "US.QQQ")},
            "canonical_cache": {x: {"bar_count_15m": 2, "bar_count_1h": 1} for x in ("US.AMD", "US.NVDA", "US.TSLA", "US.QQQ")},
            "cache_session_us": "US_RTH",
            "bar_closure": "UNPROVEN",
            "adapter_diagnostics": {},
        },
    ]
    paths = iter(payloads)
    monkeypatch.setattr("scripts.probe_us_cloud_exact._read_json", lambda path: next(paths, payloads[-1]) if "latest-heartbeat" in path else ({"expected_source_repo_sha": "b" * 40} if "research-state" in path else {"repo_sha": "a" * 40}))
    monkeypatch.setattr("scripts.probe_us_cloud_exact._now", lambda: datetime(2026, 10, 9, tzinfo=timezone.utc))
    clock = iter(range(100))
    monkeypatch.setattr("time.monotonic", lambda: next(clock))
    result = probe(expected_sha="a" * 40, duration_seconds=5, interval_seconds=0.5, sleep=lambda _: None)
    assert result["runtime_exact_sha"] == "NOT_VERIFIED"
    assert result["continuous_live_quote_sequence"]["status"] == "NOT_VERIFIED"
    assert result["latency_ms"]["provider_to_callback"]["status"] == "NOT_VERIFIED"
    assert result["radar_admission"] == "BLOCKED"


def test_probe_keeps_negative_end_label_age_out_of_latency_and_accepts_symbol_override(monkeypatch):
    payload = {
        "repo_sha": "a" * 40,
        "sequence": 4,
        "event_count": 8,
        "last_push_utc": "2026-10-09T00:00:00+00:00",
        "emitted_at_utc": "2026-10-09T00:00:00+00:00",
        "latest_k1m_time_keys": {"US.GLDM": "2026-10-09 09:30:00"},
        "k1m_currentness": {"US.GLDM": {"status": "PASS", "age_seconds": -2.5}},
        "canonical_cache": {"US.GLDM": {"bar_count_15m": 1, "bar_count_1h": 1}},
        "cache_session_us": "US_RTH",
        "bar_closure": "UNPROVEN",
        "adapter_diagnostics": {"provider_callback_latency_sample_count": 3, "provider_callback_latency_ms_max": 4.0},
        "symbols": ["US.GLDM"],
        "subscribed": ["US.GLDM"],
        "quote_right_evidence": {"query_status": "PASS"},
    }
    monkeypatch.setattr("scripts.probe_us_cloud_exact._read_json", lambda path: payload)
    monkeypatch.setattr("scripts.probe_us_cloud_exact._now", lambda: datetime(2026, 10, 9, tzinfo=timezone.utc))
    clock = iter(range(100))
    monkeypatch.setattr("time.monotonic", lambda: next(clock))
    result = probe(expected_sha="a" * 40, symbols=("US.GLDM",), duration_seconds=5, interval_seconds=0.5, sleep=lambda _: None)
    assert result["symbols"] == ["US.GLDM"]
    assert result["timestamp_freshness"]["status"] == "NOT_VERIFIED"
    assert result["latency_ms"]["provider_to_callback"]["status"] == "NOT_VERIFIED"
    assert result["latency_ms"]["end_label_age"]["per_symbol"]["US.GLDM"]["classification"] == "NEGATIVE_END_LABEL_AGE_NOT_LATENCY"
    assert result["latency_ms"]["callback_processing_only"]["status"] == "OBSERVED"
    assert result["symbol_coverage"]["per_symbol"]["US.GLDM"]["status"] == "PASS"
    assert result["holdings_integrity"]["status"] == "NOT_VERIFIED"

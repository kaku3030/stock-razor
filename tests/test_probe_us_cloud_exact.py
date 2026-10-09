from datetime import datetime, timezone

from scripts.probe_us_cloud_exact import probe


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

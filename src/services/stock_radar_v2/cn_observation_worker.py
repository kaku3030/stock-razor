"""Isolated research-only worker for cloud A-share observations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable, Mapping

from src.services.stock_radar_v2.cn_observation_analysis import (
    CnObservationAnalysisError,
    evaluate_cn_observation_payload,
)


class CnObservationWorkerError(ValueError):
    pass


def _blocked(reason: str, *, source_repo_sha: str | None = None, source_sequence: int | None = None) -> dict:
    return {
        "status": "BLOCKED",
        "source_repo_sha": source_repo_sha,
        "source_sequence": source_sequence,
        "analysis": None,
        "reasons": [reason],
        "research_only": True,
        "can_confirm_signal": False,
        "radar_admission": "BLOCKED",
        "live_trade": False,
    }


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CnObservationWorkerError("emitted_at_utc missing")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CnObservationWorkerError("emitted_at_utc invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CnObservationWorkerError("emitted_at_utc must be timezone-aware")
    return parsed.astimezone(timezone.utc)


class CnObservationRadarWorker:
    """Poll a canonical CN observation file without any provider/network access."""

    def __init__(
        self,
        *,
        expected_source_repo_sha: str,
        max_source_age_seconds: int = 180,
        max_future_skew_seconds: int = 5,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        sha = str(expected_source_repo_sha or "").strip().lower()
        if len(sha) != 40 or any(ch not in "0123456789abcdef" for ch in sha):
            raise ValueError("expected_source_repo_sha must be an exact git SHA")
        if max_source_age_seconds <= 0:
            raise ValueError("max_source_age_seconds must be positive")
        if max_future_skew_seconds < 0:
            raise ValueError("max_future_skew_seconds must be non-negative")
        self._expected_source_repo_sha = sha
        self._max_source_age_seconds = max_source_age_seconds
        self._max_future_skew_seconds = max_future_skew_seconds
        self._now = now
        self._last_runtime_instance_id: str | None = None
        self._last_sequence: int | None = None
        self._last_analysis: dict | None = None

    def poll_file(self, path: str | Path) -> dict:
        try:
            with Path(path).open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError, TypeError):
            return _blocked("SOURCE_FILE_INVALID")
        return self.evaluate_payload(payload)

    def evaluate_payload(self, payload: object) -> dict:
        if not isinstance(payload, Mapping):
            return _blocked("SOURCE_ROOT_INVALID")
        source_sha = str(payload.get("repo_sha") or "").strip().lower() or None
        sequence_raw = payload.get("sequence")
        try:
            sequence = int(sequence_raw)
        except (TypeError, ValueError):
            sequence = None
        if source_sha != self._expected_source_repo_sha:
            return _blocked(
                "SOURCE_REPO_SHA_MISMATCH",
                source_repo_sha=source_sha,
                source_sequence=sequence,
            )
        if sequence is None or sequence <= 0:
            return _blocked(
                "SOURCE_SEQUENCE_INVALID",
                source_repo_sha=source_sha,
                source_sequence=sequence,
            )
        runtime_instance_id = str(payload.get("runtime_instance_id") or "").strip()
        if not runtime_instance_id:
            return _blocked(
                "SOURCE_RUNTIME_ID_MISSING",
                source_repo_sha=source_sha,
                source_sequence=sequence,
            )
        try:
            emitted_at = _parse_time(payload.get("emitted_at_utc"))
        except CnObservationWorkerError:
            return _blocked(
                "SOURCE_EMITTED_AT_INVALID",
                source_repo_sha=source_sha,
                source_sequence=sequence,
            )
        now = self._now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now() must return a timezone-aware datetime")
        signed_age = (now.astimezone(timezone.utc) - emitted_at).total_seconds()
        if signed_age < -self._max_future_skew_seconds:
            return _blocked(
                "SOURCE_FROM_FUTURE",
                source_repo_sha=source_sha,
                source_sequence=sequence,
            )
        if signed_age > self._max_source_age_seconds:
            return _blocked(
                "SOURCE_STALE",
                source_repo_sha=source_sha,
                source_sequence=sequence,
            )

        if (
            self._last_runtime_instance_id == runtime_instance_id
            and self._last_sequence is not None
        ):
            if sequence < self._last_sequence:
                return _blocked(
                    "SOURCE_SEQUENCE_REGRESSION",
                    source_repo_sha=source_sha,
                    source_sequence=sequence,
                )
            if sequence == self._last_sequence and self._last_analysis is not None:
                return {
                    "status": "UNCHANGED",
                    "source_repo_sha": source_sha,
                    "source_runtime_instance_id": runtime_instance_id,
                    "source_sequence": sequence,
                    "source_emitted_at_utc": emitted_at.isoformat(),
                    "source_age_seconds": max(0.0, signed_age),
                    "analysis": self._last_analysis,
                    "reasons": ["SOURCE_SEQUENCE_UNCHANGED"],
                    "research_only": True,
                    "can_confirm_signal": False,
                    "radar_admission": "BLOCKED",
                    "live_trade": False,
                }

        try:
            analysis = evaluate_cn_observation_payload(payload)
        except (CnObservationAnalysisError, ValueError, TypeError) as exc:
            return _blocked(
                f"ANALYSIS_BLOCKED:{type(exc).__name__}",
                source_repo_sha=source_sha,
                source_sequence=sequence,
            )
        if not (
            analysis.get("research_only") is True
            and analysis.get("can_confirm_signal") is False
            and analysis.get("radar_admission") == "BLOCKED"
            and analysis.get("live_trade") is False
        ):
            return _blocked(
                "ANALYSIS_SAFETY_CONTRACT_VIOLATION",
                source_repo_sha=source_sha,
                source_sequence=sequence,
            )

        self._last_runtime_instance_id = runtime_instance_id
        self._last_sequence = sequence
        self._last_analysis = analysis
        return {
            "status": "PASS",
            "source_repo_sha": source_sha,
            "source_runtime_instance_id": runtime_instance_id,
            "source_sequence": sequence,
            "source_emitted_at_utc": emitted_at.isoformat(),
            "source_age_seconds": max(0.0, signed_age),
            "analysis": analysis,
            "reasons": [],
            "research_only": True,
            "can_confirm_signal": False,
            "radar_admission": "BLOCKED",
            "live_trade": False,
        }

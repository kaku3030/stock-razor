"""Fail-closed US OpenD 30-minute audit scheduling and evidence helpers."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

try:
    import exchange_calendars as xcals
except ImportError:  # pragma: no cover - exercised by the fail-closed test
    xcals = None

from engineering_autonomy.feedback_hub import FeedbackHub, FeedbackHubError

NY = ZoneInfo("America/New_York")
CALENDAR_NAME = "XNYS"
SYMBOLS = ("AAPL", "NVDA", "QQQ", "GLDM", "AMD", "TSLA", "LITE", "AAOI", "CIEN")
SLOT_GRACE_MINUTES = 10


@dataclass(frozen=True)
class ScheduleDecision:
    status: str
    eligible: bool
    now_et: str
    session_date: str
    session_open_et: str | None
    session_close_et: str | None
    slot_et: str | None
    source: str
    reason: str | None = None


def _as_et(value: Any) -> datetime:
    if hasattr(value, "tz_convert"):
        return value.tz_convert(NY).to_pydatetime()
    if isinstance(value, datetime):
        return value.astimezone(NY) if value.tzinfo else value.replace(tzinfo=NY)
    raise ValueError("calendar timestamp is not datetime-like")


def _now_et(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc).astimezone(NY)
    return now.astimezone(NY) if now.tzinfo else now.replace(tzinfo=NY)


def evaluate_schedule(now: datetime | None = None, grace_minutes: int = SLOT_GRACE_MINUTES) -> ScheduleDecision:
    """Return whether the current ET time is one scheduled RTH slot."""
    current = _now_et(now)
    base = {
        "now_et": current.isoformat(),
        "session_date": current.date().isoformat(),
        "session_open_et": None,
        "session_close_et": None,
        "slot_et": None,
        "source": f"exchange_calendars:{CALENDAR_NAME}",
    }
    if xcals is None:
        return ScheduleDecision(status="BLOCKED", eligible=False, reason="CALENDAR_UNAVAILABLE", **base)
    try:
        calendar = xcals.get_calendar(CALENDAR_NAME)
        if not calendar.is_session(current.date()):
            return ScheduleDecision(status="NON_TRADING_DAY", eligible=False, reason="NYSE_SESSION_ABSENT", **base)
        session = calendar.date_to_session(current.date(), direction="none")
        session_open = _as_et(calendar.session_open(session))
        session_close = _as_et(calendar.session_close(session))
    except Exception:
        return ScheduleDecision(status="BLOCKED", eligible=False, reason="CALENDAR_LOOKUP_FAILED", **base)

    base.update(session_open_et=session_open.isoformat(), session_close_et=session_close.isoformat())
    if current < session_open or current > session_close:
        return ScheduleDecision(status="OUTSIDE_RTH", eligible=False, reason="OUTSIDE_SESSION", **base)

    elapsed = current - session_open
    slot = session_open + timedelta(minutes=(int(elapsed.total_seconds()) // 1800) * 30)
    base["slot_et"] = slot.isoformat()
    if slot > session_close or current > slot + timedelta(minutes=grace_minutes):
        return ScheduleDecision(status="NOT_DUE", eligible=False, reason="SLOT_GRACE_EXPIRED", **base)
    return ScheduleDecision(status="DUE", eligible=True, reason=None, **base)


def _worker_id(slot_et: str) -> str:
    return f"us-opend-30m:{slot_et}"


def prepare(db_path: Path, now: datetime | None = None) -> dict[str, Any]:
    """Preflight the Hub before calendar work, then claim one deduplicated slot."""
    hub = FeedbackHub(db_path)
    try:
        preflight = hub.preflight()
        decision = evaluate_schedule(now)
        result: dict[str, Any] = {"feedback_preflight": preflight, "schedule": asdict(decision)}
        if not decision.eligible:
            return result
        source_ref = f"window:us:{decision.slot_et}"
        item = hub.submit(
            source="US_WINDOW",
            priority="P1",
            title="OpenD 30-minute read-only quality audit",
            details="Inspect existing OpenD exports and exact runtime SHA; no subscriptions, deployment, or orders.",
            evidence={"schedule": asdict(decision), "symbols": list(SYMBOLS)},
            source_ref=source_ref,
        )
        claimed = hub.claim(worker_id=_worker_id(decision.slot_et or source_ref))
        result["feedback"] = {
            "id": claimed.id if claimed else item.id,
            "worker_id": _worker_id(decision.slot_et or source_ref),
            "dedupe_key": item.dedupe_key,
            "status": claimed.status if claimed else "NOT_CLAIMED",
        }
        return result
    finally:
        hub.close()


def writeback(db_path: Path, feedback_id: str, worker_id: str, status: str, evidence: Mapping[str, Any], error: str | None = None) -> dict[str, Any]:
    hub = FeedbackHub(db_path)
    try:
        item = hub.writeback(feedback_id=feedback_id, worker_id=worker_id, status=status, evidence=evidence, error=error)
        return {"status": item.status, "feedback_id": item.id}
    finally:
        hub.close()


def summarize_probe(probe: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize evidence without upgrading absent layers to PASS."""
    closure = probe.get("bar_closure_15m_60m") if isinstance(probe.get("bar_closure_15m_60m"), Mapping) else {}
    coverage = probe.get("symbol_coverage") if isinstance(probe.get("symbol_coverage"), Mapping) else {}
    per_symbol = coverage.get("per_symbol") if isinstance(coverage.get("per_symbol"), Mapping) else {}
    dynamic_control_plane = "PASS" if per_symbol and all((row or {}).get("status") == "PASS" for row in per_symbol.values()) else "NOT_VERIFIED"
    quality = {
        "1m": (probe.get("continuous_live_quote_sequence") or {}).get("status", "NOT_VERIFIED"),
        "5m": (probe.get("bar_closure_5m") or {}).get("status", "NOT_VERIFIED"),
        "15m": closure.get("status", "NOT_VERIFIED"),
        "1h": closure.get("status", "NOT_VERIFIED"),
        "D1": (probe.get("bar_closure_d1") or {}).get("status", "NOT_VERIFIED"),
        "dynamic_subscription": "NOT_VERIFIED",
        "dynamic_subscription_control_plane": dynamic_control_plane,
        "disconnect_recovery": (probe.get("disconnect_recovery") or {}).get("status", "NOT_VERIFIED"),
        "latency": (probe.get("latency_ms") or {}).get("provider_to_callback", {}).get("status", "NOT_VERIFIED"),
        "runtime_sha": probe.get("runtime_exact_sha", "NOT_VERIFIED"),
    }
    return {
        "schema": "stock_razor_us_opend_30m_audit_v1",
        "quality": quality,
        "symbols": list(probe.get("symbols") or SYMBOLS),
        "holdings": {"status": "NOT_VERIFIED", "reason": "READ_ONLY_PROBE_DOES_NOT_READ_POSITIONS"},
        "signals": {"status": "NOT_VERIFIED", "reason": "QUALITY_AUDIT_ONLY_NO_TRADE_SIGNAL"},
        "radar_admission": "BLOCKED",
        "source_arbiter_admission": "BLOCKED",
        "paper_auto_ready": "NO",
        "live_trade": "NO",
        "trade_execution": "NO",
    }


def _main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--db", type=Path, required=True)
    prepare_parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        try:
            result = prepare(args.db)
        except FeedbackHubError as exc:
            print(f"FEEDBACK_HUB_BLOCKED={exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, sort_keys=True))
        if args.output:
            feedback = result.get("feedback") or {}
            lines = [f"eligible={str(result['schedule']['eligible']).lower()}", f"status={result['schedule']['status']}"]
            if feedback:
                lines.extend([f"feedback_id={feedback['id']}", f"worker_id={feedback['worker_id']}"])
            args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())

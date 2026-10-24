"""Windows scheduled, quote-only TickFlow research watcher; no admission."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

CN = ZoneInfo("Asia/Shanghai")
SAFE = {"radar_admission": "BLOCKED", "source_arbiter_admission": "BLOCKED",
        "paper_auto_ready": False, "live_trade": False, "bar_finality": "NOT_VERIFIED"}


def session_window(now):
    local = now.astimezone(CN)
    if local.weekday() >= 5:
        return "CLOSED"
    minute = local.hour * 60 + local.minute
    if not (570 <= minute <= 695 or 780 <= minute <= 935):
        return "CLOSED"
    # Weekday alone never proves a session. Reuse installed exchange calendar.
    try:
        import exchange_calendars as xc
        calendar = xc.get_calendar("XSHG")
        if not calendar.is_session(local.date().isoformat()):
            return "CLOSED"
    except Exception:
        return "CALENDAR_UNVERIFIED"
    return "SESSION_OBSERVATION_WINDOW"


def validate_records(records, symbols, periods):
    expected = {(s, t) for s in symbols for t in periods}
    seen = set()
    for row in records:
        if not isinstance(row, dict):
            return False
        key = (row.get("symbol"), row.get("timeframe"))
        if key not in expected or key in seen:
            return False
        seen.add(key)
        if (row.get("data_source") != "TICKFLOW_PREMIUM_DESKTOP_READONLY"
                or row.get("transport") != "OFFICIAL_PYTHON_SDK_REST"
                or row.get("sdk_version") != "0.1.25"
                or row.get("trading_admission") != "BLOCKED"
                or row.get("radar_admission") != "BLOCKED"
                or row.get("live_trade") is not False
                or row.get("provider_requests") != 1):
            return False
        if row.get("status") not in ("PASS_RESEARCH_ONLY", "PASS_PRIOR_DAILY_RESEARCH_ONLY"):
            if not (row.get("status") == "BLOCKED_UNVERIFIED"
                    and row.get("research_progress_status") == "PASS_RESEARCH_ONLY"):
                return False
        if row.get("invalid_rows", 0) or row.get("invalid_grid_rows", 0) or row.get("reordered_or_duplicate_rows", 0):
            return False
        if not row.get("data_time_utc") or not row.get("row_receipts"):
            return False
        if row.get("bar_finality") != "NOT_VERIFIED":
            return False
    return seen == expected


def compare_records(previous, current):
    """Compare original hashes only; changes can be legitimate vendor revisions."""
    old = {(r["symbol"], r["timeframe"]): r for r in previous}
    counts = {"new_labels": 0, "changed_ohlcv": 0, "latest_label_regressions": 0}
    for row in current:
        prior = old.get((row.get("symbol"), row.get("timeframe")), {})
        before = {r["bar_time_utc"]: r["ohlcv_sha256"] for r in prior.get("row_receipts", [])}
        after = {r["bar_time_utc"]: r["ohlcv_sha256"] for r in row.get("row_receipts", [])}
        counts["new_labels"] += len(after.keys() - before.keys())
        counts["changed_ohlcv"] += sum(before[t] != after[t] for t in before.keys() & after.keys())
        if prior.get("data_time_utc") and row.get("data_time_utc"):
            counts["latest_label_regressions"] += int(
                datetime.fromisoformat(row["data_time_utc"]) < datetime.fromisoformat(prior["data_time_utc"]))
    return counts


def atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as out:
            temp = Path(out.name)
            json.dump(value, out, allow_nan=False, separators=(",", ":"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def load_state(path):
    try:
        if path.stat().st_size > 4_000_000:
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def run_once(root, *, now=None, execute=False):
    now = now or datetime.now(timezone.utc)
    base = {**SAFE, "observed_at_utc": now.isoformat(),
            "market_session": session_window(now), "provider_requests": 0,
            "production_acceptance": "NOT_VERIFIED"}
    if not execute:
        return {**base, "status": "DRY_RUN"}
    if base["market_session"] != "SESSION_OBSERVATION_WINDOW":
        result = {**base, "status": "NOT_OBSERVED"}
        atomic_write(root / "latest-attempt.json", result)
        return result
    manifest = load_state(root / "deployment.json")
    try:
        for filename in ("audit_tickflow_windows_readonly.py", "run_tickflow_windows_watch.py"):
            digest = hashlib.sha256((root / filename).read_bytes()).hexdigest()
            if manifest["files"][filename] != digest:
                raise ValueError("deployment drift")
        if len(manifest["source_sha"]) != 40:
            raise ValueError("revision unavailable")
    except (KeyError, ValueError, OSError, TypeError):
        result = {**base, "status": "DEPLOYMENT_DRIFT_BLOCKED"}
        atomic_write(root / "latest-attempt.json", result)
        return result
    previous = load_state(root / "latest-poll.json")
    sequence = previous.get("sequence", 0)
    sequence = sequence + 1 if type(sequence) is int and sequence >= 0 else 1
    result = {**base, "sequence": sequence, "source_sha": manifest["source_sha"]}
    try:
        child = subprocess.run(
            [sys.executable, str(root / "audit_tickflow_windows_readonly.py"),
             "--execute", "--timeframe", "all", "--vendor-precision-research", "--research-exit"],
            capture_output=True, text=True, encoding="utf-8", timeout=190)
        # Never forward stderr or exception bodies: SDK may contain credentials.
        if len(child.stdout) > 2_000_000:
            raise ValueError("oversized output")
        records = [json.loads(line) for line in child.stdout.splitlines() if line.strip()]
        try:
            from scripts.audit_tickflow_windows_readonly import SYMBOLS, PERIOD_COUNTS
        except ModuleNotFoundError:
            from audit_tickflow_windows_readonly import SYMBOLS, PERIOD_COUNTS
        passed = child.returncode == 0 and validate_records(records, SYMBOLS, PERIOD_COUNTS)
        delta = compare_records(previous.get("records", []), records)
        passed = passed and delta["latest_label_regressions"] == 0
        result.update(status="PASS_SESSION_RESEARCH_ONLY" if passed else "DATA_QUALITY_BLOCKED",
                      records=records, child_exit=child.returncode,
                      provider_requests=sum(r.get("provider_requests", 0) for r in records),
                      comparison=delta,
                      comparison_status="OBSERVED" if previous.get("records") else "BASELINE_ONLY")
        gap = (now - datetime.fromisoformat(previous["observed_at_utc"])).total_seconds() if previous.get("observed_at_utc") else None
        result["gap_seconds"] = gap
        result["recovery_status"] = "GAP_REQUIRES_REVALIDATION" if gap is not None and gap > 300 else "NOT_PROVEN"
    except subprocess.TimeoutExpired:
        result.update(status="CHILD_TIMEOUT_BLOCKED", provider_requests=None)
    except Exception as exc:
        result.update(status="READ_OR_VALIDATION_BLOCKED", error_class=type(exc).__name__,
                      provider_requests=None)
    # Every process run creates a fresh SDK context, bounded timeouts and no SDK
    # retries. Next scheduled run revalidates all frames, never reuses prior PASS.
    atomic_write(root / "latest-attempt.json", result)
    atomic_write(root / "latest-poll.json", result)
    day = now.astimezone(CN).date().isoformat()
    target = root / "evidence" / day / (now.strftime("%H%M%S%f") + ".json")
    atomic_write(target, result)
    # Bound private retention to five observed dates, including restart history.
    folders = sorted((root / "evidence").glob("????-??-??"))
    for folder in folders[:-5]:
        for item in folder.glob("*.json"):
            item.unlink()
        try:
            folder.rmdir()
        except OSError:
            pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = run_once(args.root, execute=args.execute)
    # Console is a bounded health projection, no rows, paths or raw exceptions.
    print(json.dumps({k: result[k] for k in (
        "status", "observed_at_utc", "market_session", "provider_requests",
        "production_acceptance", "radar_admission", "live_trade")}))
    return 0 if result["status"] in ("NOT_OBSERVED", "DRY_RUN", "PASS_SESSION_RESEARCH_ONLY") else 2


if __name__ == "__main__":
    raise SystemExit(main())

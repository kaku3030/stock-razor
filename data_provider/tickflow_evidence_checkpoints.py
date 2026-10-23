"""Private, immutable TickFlow research evidence; never grants admission."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from data_provider.cn_tickflow_research_cache import (
    CN, SYMBOLS, TIMEFRAMES, _ALLOWED_PERIODS, _LABEL_END,
    _expected_closed_grid_label, read_cn_tickflow_research_data,
)

SCHEMA = "tickflow_private_evidence_v1"
ROOT = Path("/var/lib/stock-razor-cn-tickflow/evidence")
FIELDS = ("open", "high", "low", "close", "volume", "amount")
MAX_FILE = 2_000_000
MAX_STORE = 64_000_000
SAFE = {"research_only": True, "provenance_verified": False,
        "bar_finality": "NOT_VERIFIED", "source_arbiter_admission": "BLOCKED",
        "radar_admission": "BLOCKED", "live_trade": False, "provider_requests": 0,
        "canonical_write_authorized": False, "paper_auto_ready": False}


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _time(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("INVALID_CLOCK")
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("INVALID_CLOCK")
    return stamp.astimezone(timezone.utc)


def manifest_from_observation(observation, *, endpoint, now_utc):
    """Reuse the complete cache reader; store field hashes, never market values.

    Endpoint labels are capture metadata, not independently authenticated proof.
    A copied file cannot establish endpoint provenance or trading eligibility.
    """
    if endpoint not in ("AWS", "WINDOWS"):
        raise ValueError("INVALID_ENDPOINT")
    observed = _time(observation["observed_at_utc"])
    day = observed.astimezone(CN).date().isoformat()
    frames = {}
    for symbol in SYMBOLS:
        for period in TIMEFRAMES:
            read = read_cn_tickflow_research_data(symbol, period, limit=240,
                now_utc=now_utc, observation=observation,
                research_mode="historical_only" if period == "1d" else "session_progress")
            if not read.get("ok"):
                raise ValueError("UNQUALIFIED_CACHE_FRAME")
            # Pair today's full intraday grid and all validated prior D1 dates.
            rows = [r for r in read["rows"] if period == "1d" or r["label"].startswith(day)]
            frames[symbol+":"+period] = {
                r["label"]: {field: _hash(None if r.get(field) is None else
                    format(Decimal(str(r[field])).normalize(), "f")) for field in FIELDS}
                for r in rows
            }
    doc = {"schema": SCHEMA, "endpoint": endpoint, "provider": "TICKFLOW_PREMIUM",
        "source_sha": observation["repo_sha"], "sequence": observation["sequence"],
        "observed_at_utc": observed.isoformat(), "session_day": day,
        "frames": frames, **SAFE}
    doc["integrity_sha256"] = _hash(doc)
    validate_manifest(doc)
    return doc


def validate_manifest(doc):
    if not isinstance(doc, dict) or len(_encoded(doc)) > MAX_FILE:
        raise ValueError("INVALID_MANIFEST")
    if set(doc) != {"schema","endpoint","provider","source_sha","sequence",
                    "observed_at_utc","session_day","frames","integrity_sha256",*SAFE}:
        raise ValueError("INVALID_MANIFEST_SCHEMA")
    if (doc.get("schema") != SCHEMA or doc.get("endpoint") not in ("AWS", "WINDOWS")
        or doc.get("provider") != "TICKFLOW_PREMIUM"
        or not re.fullmatch("[0-9a-f]{40}", str(doc.get("source_sha")))
        or type(doc.get("sequence")) is not int or doc["sequence"] < 1
        or any(doc.get(k) != v or type(doc.get(k)) is not type(v) for k,v in SAFE.items())):
        raise ValueError("INVALID_MANIFEST")
    stamp = _time(doc["observed_at_utc"])
    if doc.get("session_day") != stamp.astimezone(CN).date().isoformat():
        raise ValueError("DAY_MISMATCH")
    frames = doc.get("frames")
    expected = {s+":"+p for s in SYMBOLS for p in TIMEFRAMES}
    if not isinstance(frames, dict) or set(frames) != expected:
        raise ValueError("FRAME_SET_MISMATCH")
    for key, rows in frames.items():
        period = key.split(":")[1]
        if not isinstance(rows, dict) or not 1 <= len(rows) <= _ALLOWED_PERIODS[period]:
            raise ValueError("FRAME_SIZE_INVALID")
        for label, hashes in rows.items():
            parsed = datetime.strptime(label, "%Y-%m-%d %H:%M")
            if parsed.strftime("%H:%M") not in _LABEL_END[period]:
                raise ValueError("FRAME_GRID_MISMATCH")
            if period != "1d" and parsed.date().isoformat() != doc["session_day"]:
                raise ValueError("FRAME_DAY_MISMATCH")
            if period == "1d" and (len(rows) != 60 or parsed.date() >= stamp.astimezone(CN).date()):
                raise ValueError("DAILY_HISTORY_INCOMPLETE")
            if (not isinstance(hashes, dict) or set(hashes) != set(FIELDS)
                    or any(not isinstance(h,str) or not re.fullmatch("[0-9a-f]{64}",h)
                           for h in hashes.values())):
                raise ValueError("FIELD_HASH_INVALID")
        if period != "1d":
            due = _expected_closed_grid_label(stamp,period)
            if due is not None:
                labels = {doc["session_day"]+" "+clock for clock in _LABEL_END[period]
                          if clock <= due.strftime("%H:%M")}
                if not labels.issubset(rows):
                    raise ValueError("DUE_GRID_INCOMPLETE")
            if any(datetime.strptime(k,"%Y-%m-%d %H:%M").replace(tzinfo=CN) > stamp
                   for k in rows):
                raise ValueError("FUTURE_LABEL")
    unsigned = {k:v for k,v in doc.items() if k != "integrity_sha256"}
    if doc.get("integrity_sha256") != _hash(unsigned):
        raise ValueError("INTEGRITY_MISMATCH")


def compare_manifests(first, second, *, dual_endpoint=False, now_utc=None):
    """Return bounded counts only; matching snapshots never prove finality."""
    try:
        validate_manifest(first)
        validate_manifest(second)
        a,b = _time(first["observed_at_utc"]), _time(second["observed_at_utc"])
        now = now_utc or datetime.now(timezone.utc)
        if type(dual_endpoint) is not bool or now.tzinfo is None or max(a,b) > now+timedelta(seconds=5):
            raise ValueError("INVALID_COMPARISON_CLOCK")
        if first["session_day"] != second["session_day"]:
            raise ValueError("DAY_MISMATCH")
        if first["source_sha"] != second["source_sha"]:
            raise ValueError("CODE_REVISION_MISMATCH")
        if dual_endpoint:
            if {first["endpoint"],second["endpoint"]} != {"AWS","WINDOWS"}:
                raise ValueError("DISTINCT_ENDPOINTS_REQUIRED")
            if abs((b-a).total_seconds()) > 30:
                raise ValueError("CAPTURE_WINDOW_MISMATCH")
        elif first["endpoint"] != second["endpoint"] or b <= a:
            raise ValueError("OBSERVATION_NOT_ADVANCING")
        added = missing = changed = 0
        fields = {f:0 for f in FIELDS}
        for key in first["frames"]:
            old,new = first["frames"][key],second["frames"][key]
            added += len(new.keys()-old.keys())
            missing += len(old.keys()-new.keys())
            for label in old.keys() & new.keys():
                diffs = [f for f in FIELDS if old[label][f] != new[label][f]]
                changed += bool(diffs)
                for field in diffs:
                    fields[field] += 1
        status = ("PAIR_VALUES_MATCH_RESEARCH_ONLY" if dual_endpoint else
                  "NO_REVISION_OBSERVED_NOT_FINAL") if not (added or missing or changed) else (
                  "PAIR_DIFFERENCE_OBSERVED" if dual_endpoint else "REVISION_OBSERVED")
        return {**SAFE, "status":status, "added_rows":added, "missing_rows":missing,
                "changed_rows":changed, "changed_fields":fields}
    except (ValueError,TypeError,KeyError,OverflowError):
        return {**SAFE, "status":"EVIDENCE_INVALID"}


def _load(path):
    with path.open("rb") as handle:
        raw = handle.read(MAX_FILE+1)
    if len(raw) > MAX_FILE:
        raise ValueError("MANIFEST_TOO_LARGE")
    doc = json.loads(raw)
    validate_manifest(doc)
    return doc


def write_immutable(path, doc):
    """Atomic create only. Existing evidence is never overwritten."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = _encoded(doc)
    if len(payload) > MAX_FILE:
        raise ValueError("MANIFEST_TOO_LARGE")
    fd,tmp = tempfile.mkstemp(dir=path.parent, prefix=".evidence-")
    try:
        os.chmod(tmp,0o600)
        with os.fdopen(fd,"wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp,path)
            if os.name != "nt":
                directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            return True
        except FileExistsError:
            return False
    finally:
        os.unlink(tmp)


def record_postclose_checkpoint(observation, *, root=ROOT, now_utc):
    """One baseline and one after-20:00 capture/day; no extra provider reads."""
    local = _time(observation["observed_at_utc"]).astimezone(CN)
    if local.weekday() >= 5 or (local.hour,local.minute) < (15,2):
        return {**SAFE,"status":"NOT_DUE"}
    phase = "baseline" if local.hour < 20 else "after20"
    day = local.date().isoformat()
    root = Path(root)
    path = root/day/(phase+".json")
    if path.exists():
        _load(path)  # A corrupt checkpoint must not silently become valid.
        return checkpoint_status(root=root, day=day, now_utc=now_utc)
    manifest = manifest_from_observation(observation,endpoint="AWS",now_utc=now_utc)
    used = sum(p.stat().st_size for p in root.glob("*/*.json")) if root.exists() else 0
    if used + len(_encoded(manifest)) > MAX_STORE:
        return {**SAFE,"status":"EVIDENCE_QUOTA_BLOCKED"}
    if not write_immutable(path,manifest):
        return {**SAFE,"status":"CHECKPOINT_ALREADY_RECORDED", "phase":phase}
    return checkpoint_status(root=root, day=day, now_utc=now_utc)


def checkpoint_status(*, root=ROOT, day, now_utc=None):
    """Read private checkpoints without provider I/O or exporting hashes."""
    if datetime.strptime(day,"%Y-%m-%d").date().isoformat() != day:
        raise ValueError("INVALID_DAY")
    root = Path(root)/day
    baseline, later = root/"baseline.json", root/"after20.json"
    if not baseline.exists():
        return {**SAFE,"status":"BASELINE_MISSING"}
    first = _load(baseline)
    observed = _time(first["observed_at_utc"]).astimezone(CN)
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None or observed > now+timedelta(seconds=5):
        raise ValueError("FUTURE_CAPTURE")
    if first["session_day"] != day or not (15,2) <= (observed.hour,observed.minute) < (20,0):
        raise ValueError("BASELINE_PHASE_INVALID")
    result = {**SAFE,"status":"BASELINE_RECORDED_AWAITING_AFTER20",
              "baseline_timing":"LATE_BASELINE_LIMITED" if
              (observed.hour,observed.minute)>(15,15) else "IN_WINDOW"}
    if later.exists():
        second = _load(later)
        if second["session_day"] != day or _time(second["observed_at_utc"]).astimezone(CN).hour < 20:
            raise ValueError("CORRECTION_PHASE_INVALID")
        result["comparison"] = compare_manifests(first,second,now_utc=now)
        result["status"] = ("POSTCLOSE_COMPARISON_BLOCKED" if
            result["comparison"]["status"] == "EVIDENCE_INVALID" else
            "POSTCLOSE_COMPARISON_RECORDED")
    return result


PAIR_SCHEMA = "tickflow_postclose_pair_summary_v1"
_PAIR_COUNTS = {"1m":240,"5m":48,"15m":16,"60m":4,"1d":60}


def pairing_summary(manifest):
    """Compact postclose fingerprints; never authenticated endpoint proof."""
    validate_manifest(manifest)
    local = _time(manifest["observed_at_utc"]).astimezone(CN)
    if local.weekday() >= 5 or (local.hour,local.minute) < (15,2):
        raise ValueError("POSTCLOSE_CAPTURE_REQUIRED")
    frames = {key:{"rows":len(rows),"sha256":_hash(rows)}
              for key,rows in manifest["frames"].items()}
    doc = {**SAFE,"schema":PAIR_SCHEMA,"endpoint":manifest["endpoint"],
           "source_sha":manifest["source_sha"],"sequence":manifest["sequence"],
           "observed_at_utc":manifest["observed_at_utc"],
           "session_day":manifest["session_day"],"frames":frames}
    _validate_pair_summary(doc)
    return doc


def _validate_pair_summary(doc):
    keys = {"schema","endpoint","source_sha","sequence","observed_at_utc",
            "session_day","frames",*SAFE}
    if not isinstance(doc,dict) or set(doc)!=keys or len(_encoded(doc))>16000:
        raise ValueError("PAIR_SCHEMA_INVALID")
    if (doc["schema"]!=PAIR_SCHEMA or doc["endpoint"] not in ("AWS","WINDOWS")
            or not isinstance(doc["source_sha"],str)
            or not re.fullmatch("[0-9a-f]{40}",doc["source_sha"])
            or type(doc["sequence"]) is not int or doc["sequence"]<1
            or any(type(doc[k]) is not type(v) or doc[k]!=v for k,v in SAFE.items())):
        raise ValueError("PAIR_METADATA_INVALID")
    local = _time(doc["observed_at_utc"]).astimezone(CN)
    if (doc["session_day"]!=local.date().isoformat() or local.weekday()>=5
            or (local.hour,local.minute)<(15,2)):
        raise ValueError("PAIR_CLOCK_INVALID")
    expected = {s+":"+p for s in SYMBOLS for p in TIMEFRAMES}
    frames = doc["frames"]
    if not isinstance(frames,dict) or set(frames)!=expected:
        raise ValueError("PAIR_FRAMES_INVALID")
    for key,value in frames.items():
        if (not isinstance(value,dict) or set(value)!={"rows","sha256"}
                or type(value["rows"]) is not int
                or value["rows"]!=_PAIR_COUNTS[key.split(":")[1]]
                or not isinstance(value["sha256"],str)
                or not re.fullmatch("[0-9a-f]{64}",value["sha256"])):
            raise ValueError("PAIR_FRAME_INVALID")


def compare_pairing_summaries(first, second, *, now_utc=None):
    """Compare two actual recent endpoint receipts; caller verifies provenance."""
    try:
        _validate_pair_summary(first)
        _validate_pair_summary(second)
        now = now_utc or datetime.now(timezone.utc)
        a,b = _time(first["observed_at_utc"]),_time(second["observed_at_utc"])
        if (now.tzinfo is None or {first["endpoint"],second["endpoint"]}!={"AWS","WINDOWS"}
                or first["source_sha"]!=second["source_sha"]
                or first["session_day"]!=second["session_day"]
                or abs((a-b).total_seconds())>30
                or max(a,b)>now+timedelta(seconds=5)
                or min(a,b)<now-timedelta(seconds=330)):
            raise ValueError("PAIR_ALIGNMENT_INVALID")
        changed = sum(first["frames"][k]!=second["frames"][k] for k in first["frames"])
        return {**SAFE,"status":"PAIR_DIFFERENCE_OBSERVED" if changed else
                "PAIR_VALUES_MATCH_RESEARCH_ONLY","frame_count":20,
                "different_frames":changed}
    except (ValueError,TypeError,KeyError,OverflowError):
        return {**SAFE,"status":"EVIDENCE_INVALID"}


def read_pairing_summary(*, path=None, now_utc=None):
    """One atomic local cache read, all20frames validated, no SDK/provider I/O."""
    from data_provider.cn_tickflow_research_cache import DEFAULT_PATH, MAX_BYTES
    try:
        with open(path or DEFAULT_PATH,"rb") as handle:
            raw=handle.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            raise ValueError("CACHE_TOO_LARGE")
        now=now_utc or datetime.now(timezone.utc)
        manifest=manifest_from_observation(json.loads(raw),endpoint="AWS",now_utc=now)
        if now-_time(manifest["observed_at_utc"])>timedelta(seconds=330):
            raise ValueError("PAIR_CACHE_STALE")
        return {**SAFE,"status":"POSTCLOSE_PAIR_CAPTURE_RESEARCH_ONLY",
                "pairing_summary":pairing_summary(manifest)}
    except OSError:
        return {**SAFE,"status":"PAIR_CACHE_IO_BLOCKED"}
    except (ValueError,TypeError,KeyError,OverflowError):
        return {**SAFE,"status":"PAIR_CACHE_VALIDATION_BLOCKED"}

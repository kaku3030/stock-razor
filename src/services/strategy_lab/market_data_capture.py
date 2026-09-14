"""Offline market-data capture into governed research capsules.

Adapters may download bytes outside this module.  This boundary accepts only a
recorded CSV payload and explicit provenance; it never polls a provider.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path

from .research_dataset import LateEventPolicy, ResearchDataEvent, ResearchDatasetCapsule
from .temporal_contract import canonical_utc_datetime


def load_recorded_capture(csv_path: str | Path, manifest_path: str | Path, *, require_pit_approved: bool = False) -> "MarketDataCapture":
    """Load one EOD capture only when its sidecar provenance verifies."""
    csv_file, manifest_file = Path(csv_path), Path(manifest_path)
    payload = csv_file.read_bytes()
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("status") != "CAPTURED_NOT_APPROVED":
        raise ValueError("capture manifest is not approved for research: " + str(manifest.get("status")))
    digest = hashlib.sha256(payload).hexdigest()
    if manifest.get("raw_sha256") != digest:
        raise ValueError("capture manifest raw_sha256 mismatch")
    retrieved = datetime.fromisoformat(manifest["retrieved_at"])
    return MarketDataCapture(
        source_id=manifest["source_id"], endpoint_id=manifest["endpoint_id"],
        adapter_version=manifest.get("adapter_version", "capture-script"),
        market=manifest["market"], retrieved_at=retrieved, available_at=retrieved,
        timezone="UTC", adjustment=manifest.get("adjustment", "unadjusted"),
        csv_text=payload.decode("utf-8"),
    )


@dataclass(frozen=True)
class MarketDataCapture:
    source_id: str
    endpoint_id: str
    adapter_version: str
    market: str
    retrieved_at: datetime
    available_at: datetime
    timezone: str
    adjustment: str
    csv_text: str

    def to_capsule(self, dataset_id: str, dataset_version: str) -> ResearchDatasetCapsule:
        if not all(isinstance(v, str) and v.strip() for v in (self.source_id, self.endpoint_id, self.adapter_version, self.market, self.timezone, self.adjustment, self.csv_text)):
            raise ValueError("capture provenance fields and csv_text must be non-empty")
        rows = list(csv.DictReader(StringIO(self.csv_text)))
        if not rows or not {"symbol", "date", "open", "high", "low", "close", "volume"}.issubset(rows[0]):
            raise ValueError("CSV must contain symbol,date,open,high,low,close,volume")
        observed = canonical_utc_datetime(self.retrieved_at)
        available = canonical_utc_datetime(self.available_at)
        events = []
        for pos, row in enumerate(rows):
            raw = ",".join(f"{k}={row[k]}" for k in sorted(row))
            digest = hashlib.sha256(raw.encode()).hexdigest()
            event_id = hashlib.sha256(f"{self.source_id}:{self.endpoint_id}:{digest}".encode()).hexdigest()
            effective = canonical_utc_datetime(datetime.fromisoformat(row["date"]).replace(tzinfo=observed.tzinfo))
            events.append(ResearchDataEvent(event_id, f"{row['symbol']}:{row['date']}", digest, effective, available, observed, pos))
        return ResearchDatasetCapsule(dataset_id, dataset_version, self.source_id, self.adapter_version, LateEventPolicy.DROP, tuple(events))

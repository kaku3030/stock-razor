"""Bind paper admission to the same qualified LiveFeed truth used by Radar."""
from __future__ import annotations
from dataclasses import dataclass
from src.services.execution_engine import ExecutionBlocked
from src.services.live_feed.admission import admit_qualified_livefeed
from src.services.live_feed.qualification import StreamQualification

@dataclass(frozen=True)
class PaperMarketDataEvidence:
    evidence_id: str
    qualification: StreamQualification

def require_qualified_market_data(evidence: PaperMarketDataEvidence) -> str:
    if not isinstance(evidence.evidence_id, str) or not evidence.evidence_id.strip():
        raise ExecutionBlocked("market-data evidence_id is required")
    admission = admit_qualified_livefeed(evidence.qualification)
    if not admission.admitted:
        raise ExecutionBlocked(f"market-data qualification blocked: {admission.reason}")
    return evidence.evidence_id.strip()

import pytest
from dataclasses import replace
from data_provider.live_feed_types import LifecycleState, SemanticStreamKey
from src.services.execution_engine import ExecutionBlocked
from src.services.live_feed.qualification import QualificationFact, QualificationStatus, StreamQualification
from src.services.paper_livefeed_admission import PaperMarketDataEvidence, require_qualified_market_data

KEY = SemanticStreamKey("moomoo_opend", "US", "AMD", "KLINE", "1m")

def qualified(**changes):
    base = StreamQualification(
        semantic_stream_key=KEY,
        lifecycle_state=LifecycleState.LIVE,
        provider_health=QualificationFact(QualificationStatus.PROVEN),
        last_bar_ts=QualificationFact(QualificationStatus.PROVEN),
        currentness=QualificationFact(QualificationStatus.PROVEN),
        continuity=QualificationFact(QualificationStatus.PROVEN),
        subscription_usage=QualificationFact(QualificationStatus.UNKNOWN),
        evidence_scope="RUNTIME_PROVIDER",
        cloud_livefeed="VERIFIED",
    )
    return replace(base, **changes)

def test_paper_rejects_synthetic_market_data():
    with pytest.raises(ExecutionBlocked, match="NON_RUNTIME_EVIDENCE_SCOPE"):
        require_qualified_market_data(PaperMarketDataEvidence("md-1", qualified(evidence_scope="SYNTHETIC_ONLY")))

def test_paper_rejects_unverified_cloud_market_data():
    with pytest.raises(ExecutionBlocked, match="CLOUD_LIVEFEED_NOT_VERIFIED"):
        require_qualified_market_data(PaperMarketDataEvidence("md-1", qualified(cloud_livefeed="NOT_VERIFIED")))

def test_paper_accepts_only_shared_qualified_livefeed_truth():
    assert require_qualified_market_data(PaperMarketDataEvidence("md-1", qualified())) == "md-1"

"""Radar-facing alias for the shared qualified LiveFeed admission truth."""
from src.services.live_feed.admission import (
    QualifiedLiveFeedAdmission as LiveFeedAdmission,
    admit_qualified_livefeed as admit_livefeed_for_radar,
)

__all__ = ["LiveFeedAdmission", "admit_livefeed_for_radar"]

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.services.a_share_reconciliation_lineage import (
    build_cn_realtime_reconciliation_view,
)
from src.services.data_capability_service import DataCapabilityService


class _Fetcher:
    def __init__(self, name: str, priority: int, available=True) -> None:
        self.name = name
        self.priority = priority
        self._available = available


class _FetcherManager:
    def __init__(self, fetchers) -> None:
        self._fetchers = list(fetchers)

    def _get_fetchers_snapshot(self):
        return list(self._fetchers)


def _config(priority: str):
    return SimpleNamespace(
        tushare_token=None,
        tickflow_api_key=None,
        tickflow_priority=2,
        futu_opend_host=None,
        longbridge_app_key=None,
        longbridge_app_secret=None,
        longbridge_access_token=None,
        longbridge_oauth_client_id=None,
        finnhub_api_key=None,
        alphavantage_api_key=None,
        enable_realtime_quote=True,
        enable_fundamental_pipeline=True,
        realtime_source_priority=priority,
        futu_hk_realtime_source_priority="futu,longbridge,akshare,yfinance",
        screening_enabled=False,
        agent_event_monitor_enabled=False,
    )


def _cn_priority_tokens(overview: dict) -> list[str]:
    priorities = {item["scenario"]: item for item in overview["priorities"]}
    return list(priorities["cn.realtime"]["providers"])


def test_eastmoney_adapter_paths_count_as_one_independent_upstream() -> None:
    view = build_cn_realtime_reconciliation_view(
        ["efinance", "akshare_em", "akshare_sina"]
    )

    assert view["source_count"] == 3
    assert view["known_lineage_source_count"] == 3
    assert view["independent_upstream_count"] == 2
    groups = {
        group["upstream_lineage_id"]: group
        for group in view["independence_groups"]
    }
    assert groups["eastmoney"]["source_tokens"] == ["efinance", "akshare_em"]
    assert groups["eastmoney"]["adapter_ids"] == ["efinance", "akshare"]
    assert groups["sina"]["source_tokens"] == ["akshare_sina"]


def test_tencent_alias_tokens_do_not_create_two_independent_votes() -> None:
    view = build_cn_realtime_reconciliation_view(["tencent", "akshare_qq"])

    assert view["source_count"] == 2
    assert view["independent_upstream_count"] == 1
    assert view["independence_groups"] == [
        {
            "upstream_lineage_id": "tencent",
            "source_tokens": ["tencent", "akshare_qq"],
            "adapter_ids": ["akshare"],
            "endpoint_ids": ["akshare.tencent_spot"],
        }
    ]


def test_unknown_lineage_is_visible_but_not_independence_eligible() -> None:
    view = build_cn_realtime_reconciliation_view(
        ["efinance", "future_provider_not_yet_registered"]
    )

    assert view["unknown_lineage_tokens"] == ["future_provider_not_yet_registered"]
    unknown = view["sources"][1]
    assert unknown["lineage_status"] == "unknown"
    assert unknown["upstream_lineage_id"] is None
    assert unknown["independence_eligible"] is False
    assert view["governance"]["unknown_lineage_independence_eligible"] is False


def test_view_preserves_existing_route_order_but_does_not_select_route() -> None:
    priority = "tencent,akshare_sina,efinance,akshare_em"
    service = DataCapabilityService(
        config=_config(priority),
        fetcher_manager=_FetcherManager(
            [
                _Fetcher("AkshareFetcher", 1),
                _Fetcher("EfinanceFetcher", 0),
            ]
        ),
    )

    before = service.get_overview()
    route = _cn_priority_tokens(before)
    view = build_cn_realtime_reconciliation_view(route)
    after = service.get_overview()

    assert route == ["tencent", "akshare_sina", "efinance", "akshare_em"]
    assert [item["source_token"] for item in view["sources"]] == route
    assert _cn_priority_tokens(after) == route
    assert view["governance"]["changes_provider_selection"] is False
    assert view["governance"]["decision_weighting"] == "NONE"


def test_lineage_view_does_not_mutate_existing_dataset_quality_truth() -> None:
    service = DataCapabilityService(
        config=_config("efinance,tencent"),
        fetcher_manager=_FetcherManager(
            [
                _Fetcher("EfinanceFetcher", 0),
                _Fetcher("AkshareFetcher", 1),
            ]
        ),
    )
    before = service.get_overview()

    build_cn_realtime_reconciliation_view(_cn_priority_tokens(before))

    after = service.get_overview()
    assert before["providers"] == after["providers"]
    assert before["datasets"] == after["datasets"]
    assert before["priorities"] == after["priorities"]
    assert before["warnings"] == after["warnings"]


def test_duplicate_or_malformed_route_tokens_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        build_cn_realtime_reconciliation_view(["efinance", "efinance"])

    with pytest.raises(ValueError, match="trimmed"):
        build_cn_realtime_reconciliation_view([" efinance"])

    with pytest.raises(ValueError, match="iterable"):
        build_cn_realtime_reconciliation_view("efinance")

    with pytest.raises(ValueError, match="trimmed"):
        build_cn_realtime_reconciliation_view([["efinance"]])


def test_json_surface_contains_no_secrets_or_numeric_decision_weight() -> None:
    view = build_cn_realtime_reconciliation_view(
        ["tickflow", "tushare", "efinance"]
    )
    encoded = json.dumps(view, ensure_ascii=False, sort_keys=True).lower()

    for forbidden in ("api_key", "password", "credential", "secret_value"):
        assert forbidden not in encoded
    assert view["governance"]["decision_weighting"] == "NONE"
    for source in view["sources"]:
        assert "weight" not in source
    for group in view["independence_groups"]:
        assert "weight" not in group

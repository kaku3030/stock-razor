from dataclasses import FrozenInstanceError
import json

import pytest

from src.services.a_share_provider_lineage import (
    CN_REALTIME_SOURCE_LINEAGE,
    RealtimeSourceLineage,
    get_cn_realtime_source_lineage,
)
from src.services.data_capability_service import _CN_REALTIME_SOURCES


def test_lineage_manifest_exactly_matches_admitted_cn_realtime_tokens() -> None:
    assert set(CN_REALTIME_SOURCE_LINEAGE) == set(_CN_REALTIME_SOURCES)


def test_every_manifest_key_matches_its_embedded_source_token() -> None:
    for token, lineage in CN_REALTIME_SOURCE_LINEAGE.items():
        assert lineage.source_token == token
        assert lineage.markets == ("cn",)


def test_eastmoney_wrappers_are_not_falsely_independent() -> None:
    efinance = CN_REALTIME_SOURCE_LINEAGE["efinance"]
    akshare_em = CN_REALTIME_SOURCE_LINEAGE["akshare_em"]

    assert efinance.adapter_id == "efinance"
    assert akshare_em.adapter_id == "akshare"
    assert efinance.adapter_id != akshare_em.adapter_id
    assert efinance.upstream_lineage_id == "eastmoney"
    assert akshare_em.upstream_lineage_id == "eastmoney"


def test_tencent_realtime_aliases_are_explicitly_same_upstream_path() -> None:
    qq = CN_REALTIME_SOURCE_LINEAGE["akshare_qq"]
    tencent = CN_REALTIME_SOURCE_LINEAGE["tencent"]

    assert qq.adapter_id == "akshare"
    assert tencent.adapter_id == "akshare"
    assert qq.upstream_lineage_id == tencent.upstream_lineage_id == "tencent"
    assert qq.endpoint_id == tencent.endpoint_id == "akshare.tencent_spot"


def test_realtime_tencent_token_does_not_claim_tencent_direct_adapter() -> None:
    lineage = CN_REALTIME_SOURCE_LINEAGE["tencent"]
    assert lineage.adapter_id != "tencent_direct"
    assert lineage.adapter_id != "TencentFetcher"


def test_structured_sources_retain_own_lineage() -> None:
    assert CN_REALTIME_SOURCE_LINEAGE["tickflow"].upstream_lineage_id == "tickflow"
    assert CN_REALTIME_SOURCE_LINEAGE["tushare"].upstream_lineage_id == "tushare"


def test_lineage_objects_are_frozen_and_manifest_is_read_only() -> None:
    lineage = CN_REALTIME_SOURCE_LINEAGE["efinance"]
    with pytest.raises(FrozenInstanceError):
        lineage.adapter_id = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        CN_REALTIME_SOURCE_LINEAGE["new"] = lineage  # type: ignore[index]


def test_json_ready_output_is_deterministic_and_contains_no_secrets() -> None:
    first = get_cn_realtime_source_lineage()
    second = get_cn_realtime_source_lineage()

    assert first == second
    assert [item["source_token"] for item in first] == sorted(_CN_REALTIME_SOURCES)
    encoded = json.dumps(first, ensure_ascii=False, sort_keys=True).lower()
    for forbidden in ("api_key", "token_value", "password", "secret", "credential"):
        assert forbidden not in encoded


def test_lineage_validation_rejects_ambiguous_shapes() -> None:
    with pytest.raises(ValueError, match="adapter_id"):
        RealtimeSourceLineage(
            source_token="source",
            adapter_id="",
            upstream_lineage_id="upstream",
            endpoint_id="endpoint",
            markets=("cn",),
        )

    with pytest.raises(ValueError, match="duplicates"):
        RealtimeSourceLineage(
            source_token="source",
            adapter_id="adapter",
            upstream_lineage_id="upstream",
            endpoint_id="endpoint",
            markets=("cn", "cn"),
        )

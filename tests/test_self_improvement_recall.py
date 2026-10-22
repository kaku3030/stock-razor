"""Deterministic cross-window retrieval of similar past failures, with strict evidence gates."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.self_improvement_gate import load_registry
from scripts.self_improvement_recall import (
    ASSOCIATIONS, RecallError, load_associations, recall,
)

REGISTRY = load_registry()
HINTS = load_associations(registry=REGISTRY)


def search(query):
    return recall(query, registry=REGISTRY, associations=HINTS)


@pytest.mark.parametrize("query,expected", [
    ("云端 OpenD D1 日线接口不支持，mcp不支持日线", "US-001"),
    ("The provider bar closure is UNPROVEN again", "US-002"),
    ("QQQ vwap超出高低价，不知金额单位", "US-003"),
    ("Radar 快照序列不一致：雷达序列不同步", "US-004"),
    ("我睡觉 Discord没有消息，webhook无回执", "US-005"),
    ("60m ROW_COUNT_BELOW_MIN S1_60M_NORMALIZE", "CN-001"),
    ("518880.SH 用了腾讯数据 tencent fallback", "CN-002"),
    ("klines.get intraday endpoint 分钟线错用接口", "CN-003"),
    ("TickFlow historical warmup rows below minimum current session only", "CN-009"),
    ("CI绿灯但不能使用，业务验收没过", "ENG-001"),
    ("部署SHA不一致, worker sha mismatch", "ENG-002"),
    ("相同SHA又失败，重复试探 没新变化", "ENG-003"),
    ("OpenD 心跳正常但没有新行情，healthy heartbeat stale bars", "ENG-004"),
    ("registry signature invalid 带点符号被拒绝", "ENG-005"),
])
def test_associative_bilingual_recall(query, expected):
    result = search(query)
    assert result["status"] == "RELATED_CASES_FOUND"
    assert expected in [x["id"] for x in result["results"]]
    assert result["verified_root_cause"] is False
    assert result["may_autonomously_trade"] is False
    assert result["automated_retry_permission"] == "NOT_GRANTED"


def test_graph_links_hint_around_existing_incident():
    result = search("vwap超出高低价")
    assert result["results"][0]["id"] == "US-003"
    links = {x["id"] for x in result["related_cases"]}
    assert "US-004" in links
    assert all(x["relationship"] == "POSSIBLY_RELATED_NOT_PROVEN"
               for x in result["related_cases"])


def test_new_unknown_error_is_not_made_into_guess():
    result = search("奇特的XYZ实验故障，之前完全没见过")
    assert result["status"] == "UNKNOWN_NEW_CASE_NEEDS_RECEIPT"
    assert result["results"] == []
    assert result["next_step_if_unknown"] == "CAPTURE_SANITIZED_FAILURE_RECEIPT_THEN_DIAGNOSE"


def test_short_generic_ci_hint_not_proven_root_cause():
    result = search("CI")
    assert result["verified_root_cause"] is False
    assert result["automated_retry_permission"] == "NOT_GRANTED"


def test_does_not_match_short_ascii_inside_other_words():
    result = search("This special object")  # 'CI' is embedded in 'special'.
    assert all(x["id"] != "ENG-001" for x in result["results"])


def test_new_registered_incident_without_association_still_lookup():
    augmented = copy.deepcopy(REGISTRY)
    new = copy.deepcopy(augmented["records"][0])
    new["id"] = "ENG-077"
    new["signature_tokens"] = ["FUTURE_FAILURE_UNSEEN"]
    augmented["records"].append(new)
    hints = load_associations(registry=augmented)
    result = recall("FUTURE_FAILURE_UNSEEN", registry=augmented, associations=hints)
    assert result["results"][0]["id"] == "ENG-077"


def test_invalid_association_reference_fails_closed(tmp_path):
    mapping = copy.deepcopy(HINTS)
    mapping["cases"][0]["related"].append("UNVERIFIED-999")
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    with pytest.raises(RecallError, match="LINKS_INVALID"):
        load_associations(path=path, registry=REGISTRY)


def test_duplicate_case_id_fails_closed(tmp_path):
    mapping = copy.deepcopy(HINTS)
    mapping["cases"].append(copy.deepcopy(mapping["cases"][0]))
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    with pytest.raises(RecallError, match="UNKNOWN_OR_DUPLICATE_ID"):
        load_associations(path=path, registry=REGISTRY)


def test_associations_check_cli_with_bounded_output():
    r = subprocess.run([sys.executable, "scripts/self_improvement_recall.py",
                        "--check-associations"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["linked_cases"] >= 13
    assert len(r.stdout) < 220


def test_recall_cli_reports_only_verified_past_evidence():
    r = subprocess.run([sys.executable, "scripts/self_improvement_recall.py",
                        "--query", "OpenD VWAP outside bar range"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    report = json.loads(r.stdout)
    assert report["results"][0]["id"] == "US-003"
    assert report["verified_root_cause"] is False
    assert len(r.stdout) < 14000


def test_no_secret_echo_and_no_network_or_model_calls():
    script = (Path("scripts") / "self_improvement_recall.py").read_text(encoding="utf-8")
    assert "requests." not in script
    assert "urllib.request" not in script
    assert "openai" not in script.lower()
    assert "subprocess" not in script
    assert "write_text" not in script


@pytest.mark.parametrize("bad_query", ["", "X", "Z" * 1501, None])
def test_invalid_query_refused(bad_query):
    with pytest.raises(RecallError, match="RECALL_QUERY_INVALID"):
        recall(bad_query, registry=REGISTRY, associations=HINTS)

"""Protect the user-ordered OpenD local-first and session-scoped cloud closeout."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
SKILL = (ROOT / ".claude/skills/stock-razor-self-improvement/SKILL.md").read_text(encoding="utf-8")
PLAN = (ROOT / "docs/operations/us-opend-local-first-cloud-acceptance-20261019.md").read_text(encoding="utf-8")


def test_default_local_p0_cloud_p1_and_rth_cloud_witness():
    assert "Windows 本地 OpenD P0" in AGENTS
    assert "AWS OpenD 实盘取证 P0-RTH" in AGENTS
    assert "AWS/OpenD P1" in AGENTS
    assert "local OpenD P0 completion" in SKILL
    assert "AWS/cloud OpenD P1" in SKILL
    assert "P0-RTH" in SKILL
    assert AGENTS.index("Windows 本地 OpenD P0") < AGENTS.index("AWS OpenD 实盘取证 P0-RTH")


def test_all_local_and_cloud_gates_are_independently_accounted():
    for stage in ("**L0**", "**L1**", "**L2**", "**C0 (RTH)**",
                  "**C1 (after L2)**", "**C2**"):
        assert stage in PLAN, stage
    for period in ("1m", "5m", "15m", "1H", "D1"):
        assert period in PLAN
    assert "QOT_RIGHT" in PLAN
    assert "RADAR_CURRENT_POLL_NOT_VALID" in PLAN
    assert "bar_closure=UNPROVEN" in PLAN
    assert "LOCAL_RUNTIME_UNAVAILABLE" in PLAN
    assert "reconnect" in PLAN.lower()
    assert "LOCAL_RUNTIME_UNAVAILABLE" in PLAN
    assert "WINDOWS_GATE" in SKILL and "AWS_GATE" in SKILL


def test_no_business_acceptance_inferred_from_process_or_heartbeat():
    assert "本地端口在监听不代表取价成功" in AGENTS
    assert "CI green + successful AWS command" in PLAN
    assert "RADAR_ADMISSION=BLOCKED" in PLAN
    assert "LIVE_TRADE=NO" in PLAN
    assert "No new paid data, keys, subscriptions, IAM changes or orders" in PLAN
    assert "unmerged" in PLAN.lower()
    assert "#749" in PLAN and "#851" in PLAN


def test_no_duplicated_priorities_database():
    # AGENTS is canonical; the dated plan and skill are execution instructions,
    # not another scheduling daemon or competing mutable priority registry.
    assert "Canonical priority:" in PLAN
    assert "not" in PLAN.lower()
    assert "TickFlow" in PLAN

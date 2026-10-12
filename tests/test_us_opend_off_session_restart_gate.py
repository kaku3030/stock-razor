"""Executable, synthetic checks of the real AWS RTH startup guards.

No cloud network, OpenD, AWS, broker, deployment or market SDK calls.
"""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


INSTALLER = Path("ops/aws/install_us_opend_livefeed.sh")
VERIFY = Path("ops/aws/verify_us_opend_livefeed.sh")


def _embedded():
    script = INSTALLER.read_text(encoding="utf-8")
    marker = 'cat >"$INSTALL_ROOT/run.py" <<\'PY\'\n'
    return script.split(marker, 1)[1].split("\nPY\n", 1)[0]


def _startup_expression():
    source = _embedded()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if any(
            isinstance(x, ast.Raise)
            and isinstance(x.exc, ast.Call)
            and any(
                isinstance(arg, ast.Constant)
                and arg.value == "US_OPEND_STARTUP_CALLBACK_STARVATION"
                for arg in x.exc.args
            )
            for x in node.body
        ):
            return compile(ast.Expression(node.test), "<startup-if>", "eval")
    raise AssertionError("No startup callback guard found")


@pytest.mark.parametrize(
    "market_state,ret,observed_events,age,expected",
    [
        ("regular", 0, 0, 20.0, True),
        ("regular", 0, 0, 19.9, False),
        ("regular", 0, 1, 30.0, False),
        ("regular", -1, 0, 30.0, False),
        ("closed", 0, 0, 30.0, False),
        ("premarket", 0, 0, 30.0, False),
        ("afterhours", 0, 0, 30.0, False),
        ("overnight", 0, 0, 30.0, False),
        ("unknown", -1, 0, 30.0, False),
    ],
)
def test_embedded_aws_callback_starvation_requires_confirmed_regular_session(
    market_state, ret, observed_events, age, expected,
):
    condition = _startup_expression()
    clock = SimpleNamespace(monotonic=lambda: age)
    futu = SimpleNamespace(RET_OK=0)
    context = {
        "ft": futu,
        "time": clock,
        "data_event_count": observed_events,
        "cache_session": market_state,
        "state_ret": ret,
        "startup_monotonic": 0.0,
        "startup_callback_deadline_seconds": 20,
    }
    assert bool(eval(condition, {"__builtins__": {}}, context)) is expected


def _verify_callback_segment():
    script = VERIFY.read_text(encoding="utf-8")
    start = script.index("# No RTH minute callbacks are required")
    end = script.index("\nwarm_start =", start)
    code = script[start:end]
    compile(code, "<verify-callbacks>", "exec")
    return code


@pytest.mark.parametrize(
    "state,status,events,accepted",
    [
        ("regular", "PASS", 0, False),
        ("afterhours", "PASS", 0, True),
        ("overnight", "PASS", 0, True),
        ("premarket", "PASS", 0, True),
        ("closed", "PASS", 0, True),
        ("unknown", "BLOCKED", 0, False),
        ("afterhours", "BLOCKED", 0, False),
        ("regular", "PASS", 1, True),
    ],
)
def test_real_aws_verifier_allows_empty_history_only_when_session_confirmed(
    state, status, events, accepted,
):
    heartbeat = {
        "event_count": events,
        "market_state_evidence": status,
        "cache_session_us": state,
    }
    if accepted:
        exec(_verify_callback_segment(), {"heartbeat": heartbeat})
    else:
        with pytest.raises(AssertionError):
            exec(_verify_callback_segment(), {"heartbeat": heartbeat})


def test_verified_closed_session_still_requires_other_deployment_evidence():
    verifier = VERIFY.read_text(encoding="utf-8")
    assert 'warm_start.get("status") == "PASS"' in verifier
    assert 'daily_summary.get("status") == "PASS"' in verifier
    assert 'heartbeat.get("radar_admission") == "BLOCKED"' in verifier
    assert 'heartbeat.get("live_trade") is False' in verifier
    assert 'heartbeat.get("bar_closure") == expected_bar_closure' in verifier
    assert 'candidate.get("provider_calls")' in verifier
    assert "OPEND_CANDIDATE_PREVIEW=READONLY_PASS" in verifier
    assert 'heartbeat.get("repo_sha") == expected_sha' in verifier
    assert "OpenUSTradeContext" not in _embedded()

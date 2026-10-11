"""Prevent external-Paper account identities from leaking via public CI logs."""

from pathlib import Path
import textwrap

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/aws-ssm-sim-account-discovery.yml"
)


def _candidate_counter():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("          def count_sim_us_rows(data):")
    end = workflow.index("\n          ctx = None", start)
    source = textwrap.dedent(workflow[start:end])
    namespace = {}
    exec(compile(source, str(WORKFLOW), "exec"), namespace)
    return namespace["count_sim_us_rows"]


class FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        assert orient == "records"
        return self.rows


def test_cloud_discovery_requires_us_stock_and_option_account_subtype():
    count = _candidate_counter()
    rows = FakeRows([
        {"acc_id": 123456789, "trd_env": "SIMULATE",
         "trdmarket_auth": ["US"], "sim_acc_type": "STOCK_AND_OPTION",
         "acc_status": "ACTIVE"},
        {"acc_id": 987654321, "trd_env": "REAL",
         "trdmarket_auth": ["US"]},
        {"acc_id": 222222222, "trd_env": "SIMULATE",
         "trdmarket_auth": ["HK"]},
    ])
    assert count(rows) == 1
    assert count(FakeRows([
        {"acc_id": 1, "trd_env": "SIMULATE", "trdmarket_auth": ["US"],
         "sim_acc_type": "STOCK", "acc_status": "ACTIVE"},
        {"acc_id": 2, "trd_env": "SIMULATE", "trdmarket_auth": ["US"],
         "sim_acc_type": "STOCK_AND_OPTION", "acc_status": "ACTIVE"},
    ])) == 1


def test_malformed_or_absent_market_auth_is_not_promoted():
    count = _candidate_counter()
    assert count(FakeRows([
        {"acc_id": 3, "trd_env": "SIMULATE", "market": "US"},
        {"acc_id": 4, "trd_env": "SIMULATE", "trdmarket_auth": "US"},
        {"acc_id": 5, "trd_env": "SIMULATE", "trdmarket_auth": None},
        {"acc_id": 6, "trd_env": "SIMULATE", "trdmarket_auth": []},
        {"acc_id": 7, "trd_env": "SIMULATE", "trdmarket_auth": ["US"],
         "sim_acc_type": "FUTURES", "acc_status": "ACTIVE"},
        {"acc_id": 8, "trd_env": "SIMULATE", "trdmarket_auth": ["US"],
         "sim_acc_type": "STOCK", "acc_status": "DISABLED"},
    ])) == 0
    assert count(object()) == 0


def test_workflow_prints_only_allowlisted_sanitized_summary():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "SIM_ACCOUNT_DISCOVERY_SUMMARY=" in source
    assert '--query StandardOutputContent --output text' in source
    assert '--argjson v' in source
    assert 'out["opend_reachable"] = (ret == ft.RET_OK)' in source
    assert "$v.probe" in source
    assert 'SOURCE_SHA: ${{ github.sha }}' in source
    assert '"observed_at_utc"' in source
    assert 'source_revision:' in source
    assert 'echo "SIM_ACCOUNT_DISCOVERY_SUMMARY=$safe"' in source
    assert 'echo "SIM_DISCOVERY_SSM_STATUS=$status"' in source
    assert '"simulated_us_account_ids"' not in source
    assert '"accounts": rows' not in source
    assert '"account_evidence"] = "PASS"' not in source
    assert "StandardErrorContent:StandardErrorContent" not in source
    assert 'printf \'%s\\n\' "$invocation"' not in source
    assert "LIVE_TRADE=NO" in source
    assert "ACCOUNT_MUTATIONS=NONE" in source

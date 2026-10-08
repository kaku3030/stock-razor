from pathlib import Path

import yaml


WORKFLOW = Path(".github/workflows/benchmark-cloud-fast-path-readonly.yml").read_text(
    encoding="utf-8"
)


def test_cloud_benchmark_yaml_parses_and_uses_bounded_workflow_dispatch():
    value = yaml.safe_load(WORKFLOW)
    assert value["name"] == "Benchmark AWS Cloud Fast-Path Reads"
    assert value["permissions"] == {"id-token": "write", "contents": "read"}
    assert "aws-actions/configure-aws-credentials@v4" in WORKFLOW
    assert "AWS-RunShellScript" in WORKFLOW
    assert "ssm send-command" in WORKFLOW
    assert "--timeout-seconds 120" in WORKFLOW


def test_cloud_benchmark_uses_existing_readonly_runtime_and_exact_sha():
    assert "/opt/stock-razor-mcp/repo" in WORKFLOW
    assert "/opt/stock-razor-mcp/venv/bin/python" in WORKFLOW
    assert "scripts/benchmark_cloud_fast_path_reads.py" in WORKFLOW
    assert 'deployed_sha="$(git rev-parse HEAD)"' in WORKFLOW
    assert 'DEPLOYED_SHA="$deployed_sha"' in WORKFLOW
    assert '"runtime_repo_sha":os.environ.get("DEPLOYED_SHA")' in WORKFLOW
    assert "--iterations 30" in WORKFLOW
    assert "AMD NVDA TSLA QQQ" in WORKFLOW
    assert "159611 518880" in WORKFLOW


def test_only_aggregate_latency_diagnostics_are_printed():
    assert '"measurement_scope":"REPEATED_READ_DIAGNOSTICS_ONLY"' in WORKFLOW
    assert '"percentiles_not_provider_slo":True' in WORKFLOW
    assert 'summary=data["summary"]' in WORKFLOW
    assert "print(json.dumps(report,sort_keys=True))" in WORKFLOW
    assert "AWS_READ_BENCHMARK_SLO_QUALIFIED=NO" in WORKFLOW
    assert "PROVIDER_AND_END_TO_END_SLO=NOT_VERIFIED" in WORKFLOW
    assert '"radar_admission":"BLOCKED"' in WORKFLOW
    assert '"live_trade":"NO"' in WORKFLOW
    assert '"off_pc_independent_acquisition":"NOT_VERIFIED"' in WORKFLOW


def test_cloud_benchmark_never_changes_running_services_or_trades():
    for unsafe in (
        "systemctl restart", "systemctl stop", "pip install",
        "OpenUSTradeContext", "OpenSecTradeContext", "submit_order",
        "place_order", "LIVE_TRADE=YES",
    ):
        assert unsafe not in WORKFLOW


def test_cloud_benchmark_surfaces_cn_per_symbol_qualification_and_read_success():
    assert 'diagnostics=data.get("cn_symbol_read_diagnostics")' in WORKFLOW
    assert '"read_success_rate":summary["success_rate"]' in WORKFLOW
    assert '"cn_symbol_read_diagnostics":diagnostics' in WORKFLOW
    assert '"CN_READ_ONLY_SOURCE_DIAGNOSTIC_NOT_ADMISSION"' in WORKFLOW
    assert '"data_qualification") == "NOT_VERIFIED"' in WORKFLOW
    assert 'set(diagnostics.get("symbols",{})) == {"159611","518880"}' in WORKFLOW
    assert 'row.get("can_confirm_signal") is False' in WORKFLOW

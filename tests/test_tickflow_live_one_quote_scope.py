"""TickFlow live quote-only route: simulated SDK, strict one batch, zero writes."""
import json
from pathlib import Path

import pytest

from scripts import probe_tickflow_isolated as probe


class LimitedQuotes:
    count = 0

    def get(self, *, symbols):
        LimitedQuotes.count += 1
        assert symbols == ["159611.SZ", "518880.SH"]
        return [
            {"symbol": "159611.SZ", "last_price": 1.23, "api_key": "SECRET_DO_NOT_LEAK"},
            {"symbol": "518880.SH", "last_price": 8.76, "api_key": "SECRET_DO_NOT_LEAK"},
        ]


class NeverCall:
    def __getattr__(self, _name):
        raise AssertionError("Unapproved TickFlow API surface invoked")


class OnlyQuotes:
    def __init__(self):
        self.quotes = LimitedQuotes()
        self.klines = NeverCall()
        self.depth = NeverCall()
        self.stream = NeverCall()


def test_exact_one_quote_batch_no_klines_depth_or_websocket():
    LimitedQuotes.count = 0
    result = probe.build_probe(
        mode="premium", symbols=("159611.SZ", "518880.SH"),
        quote_only=True, ws_seconds=0,
        client_factory=OnlyQuotes, credential_present=True,
    )
    assert LimitedQuotes.count == 1
    assert result["request_scope"] == "ONE_REALTIME_QUOTE_BATCH_ONLY"
    assert [x["name"] for x in result["operations"]] == [
        "sdk_import", "realtime_quote",
    ]
    assert result["operations"][1]["operation"] == "COMPLETED"
    assert result["operations"][1]["row_count"] == 2
    assert result["data_qualification"] == "NOT_VERIFIED"
    assert result["source_arbiter_admission"] == "BLOCKED"
    assert result["radar_admission"] == "BLOCKED"
    assert result["canonical_write"] is False
    assert result["order_execution"] is False
    assert result["live_trade"] is False
    raw = json.dumps(result)
    assert "SECRET_DO_NOT_LEAK" not in raw
    assert "last_price" not in raw
    assert '"1.23"' not in raw


@pytest.mark.parametrize("bad", [
    {"quote_only":True,"mode":"free","ws_seconds":0},
    {"quote_only":True,"mode":"metadata","ws_seconds":0},
    {"quote_only":True,"mode":"premium","ws_seconds":10},
    {"quote_only":"true","mode":"premium","ws_seconds":0},
])
def test_scope_cannot_be_inferred_from_wrong_mode_or_websocket(bad):
    with pytest.raises(ValueError):
        probe.build_probe(
            symbols=("159611.SZ",),client_factory=OnlyQuotes,
            credential_present=True,**bad,
        )


def test_one_quote_rejects_wide_universe_before_client_initialization():
    with pytest.raises(ValueError):
        probe.build_probe(
            mode="premium",symbols=("159611.SZ","518880.SH","512730.SH"),
            quote_only=True,client_factory=NeverCall,credential_present=True,
        )


def test_missing_credential_skips_with_no_provider_calls():
    LimitedQuotes.count = 0
    result = probe.build_probe(
        mode="premium",symbols=("159611.SZ","518880.SH"),
        quote_only=True,client_factory=OnlyQuotes,credential_present=False,
    )
    assert LimitedQuotes.count == 0
    assert result["operations"][-1]["operation"] == "SKIPPED"
    assert result["operations"][-1]["reason"] == "NO_API_KEY"
    assert result["radar_admission"] == "BLOCKED"


def test_aws_workflow_default_one_quote_requires_separate_explicit_full_probe():
    wf=Path(".github/workflows/probe-tickflow-aws-premium.yml").read_text()
    script=Path("ops/aws/run_tickflow_premium_probe.sh").read_text()
    assert "quote_only:" in wf
    assert "default: true" in wf
    assert 'QUOTE_ONLY: ${{ inputs.quote_only }}' in wf
    assert "TICKFLOW_PREMIUM_QUOTE_ONLY_FORBIDS_WS" in wf
    assert "if [[ \"$quote_only\" == true ]]; then" in script
    assert "probe_args+=(--quote-only)" in script
    assert 'result="$("$venv/bin/python" "$stage/probe.py" "${probe_args[@]}" 2>"$stage/probe-stderr")"' in script
    assert "TICKFLOW_ONE_QUOTE_SCOPE=" in script
    assert "NO_NETWORK" not in wf  # Provider network is an explicit opt-in.
    assert "canonical_write" in script
    assert "source_arbiter_admission" in script
    assert "radar_admission" in script
    assert "live_trade" in script




def test_tickflow_aws_bootstrap_uses_pinned_sdk_and_no_large_cli_archive():
    bootstrap = Path("ops/aws/run_tickflow_premium_probe.sh").read_text(encoding="utf-8")
    requirements = Path("ops/requirements/tickflow-isolated-v0.1.txt").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/probe-tickflow-aws-premium.yml").read_text(encoding="utf-8")

    assert "boto3==1.43.114" in requirements
    assert "botocore==1.43.114" in requirements
    assert "VERIFY_AWS_SDK" in bootstrap
    assert "aws_secrets_manager_get.py" in bootstrap
    assert "awscliv2.zip" not in bootstrap
    assert "awscli-installer" not in bootstrap
    assert "AWS_SDK=(AVAILABLE|UNAVAILABLE)" in workflow
    assert "TICKFLOW_PREMIUM_PROBE_ENABLED" in bootstrap


def test_embedded_secretsmanager_helper_emits_only_secret_or_safe_error():
    import io

    bootstrap = Path("ops/aws/run_tickflow_premium_probe.sh").read_text(encoding="utf-8")
    marker = 'cat > "$stage/aws_secrets_manager_get.py" <<\'PY\'\n'
    start = bootstrap.index(marker) + len(marker)
    end = bootstrap.index("\nPY\n", start)
    source = bootstrap[start:end]
    namespace = {"__name__": "tickflow_secret_helper_test"}
    exec(compile(source, "aws_secrets_manager_get.py", "exec"), namespace)

    class SecretClient:
        def get_secret_value(self, *, SecretId):
            assert SecretId == "stock-razor/tickflow/premium-api-key"
            return {"SecretString": '{"api_key":"test-secret"}'}

    output = io.StringIO()
    errors = io.StringIO()
    rc = namespace["main"](
        "stock-razor/tickflow/premium-api-key",
        client_factory=lambda service, **kwargs: SecretClient(),
        stdout=output, stderr=errors,
    )
    assert rc == 0
    assert output.getvalue() == '{"api_key":"test-secret"}'
    assert errors.getvalue() == ""

    class PrivateFailure(Exception):
        response = {"Error": {"Code": "AccessDeniedException"}}

        def __str__(self):
            return "PRIVATE_RAW_ERROR_TEXT"

    class DeniedClient:
        def get_secret_value(self, *, SecretId):
            raise PrivateFailure()

    output = io.StringIO()
    errors = io.StringIO()
    rc = namespace["main"](
        "stock-razor/tickflow/premium-api-key",
        client_factory=lambda service, **kwargs: DeniedClient(),
        stdout=output, stderr=errors,
    )
    assert rc == 1
    assert output.getvalue() == ""
    assert errors.getvalue().strip() == "TICKFLOW_SECRET_ERROR_CLASS=ACCESS_DENIED"
    assert "PRIVATE_RAW_ERROR_TEXT" not in errors.getvalue()

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



def test_tickflow_aws_cli_archive_retry_cleans_partial_extract_and_classifies_io(tmp_path):
    import re
    import subprocess
    import sys
    import zipfile

    bootstrap = Path("ops/aws/run_tickflow_premium_probe.sh").read_text(encoding="utf-8")
    workflow = Path(".github/workflows/probe-tickflow-aws-premium.yml").read_text(encoding="utf-8")

    retry_start = bootstrap.index("  for attempt in 1 2 3; do")
    retry_end = bootstrap.index("\n  done", retry_start)
    retry = bootstrap[retry_start:retry_end]
    cleanup = 'rm -rf "$stage/awscli-installer"'
    validator = "python3 - \"$stage/awscliv2.zip\" \"$stage/awscli-installer\" <<'PY'"
    assert cleanup in retry
    assert retry.index(cleanup) < retry.index(validator)
    assert 'archive_status=DOWNLOAD_FAILED' in retry
    assert "except OSError as exc:" in retry
    assert "errno.ENOSPC" in retry and 'print("NO_SPACE")' in retry
    assert "errno.EIO" in retry and 'print("IO_ERROR")' in retry
    assert "TICKFLOW_PREMIUM_AWS_CLI_ARCHIVE=(PASS|CRC_FAILURE|INVALID_ZIP|NO_SPACE|IO_ERROR|PERMISSION_ERROR|OS_ERROR|EXTRACTION_IO_ERROR|ARCHIVE_ERROR|DOWNLOAD_FAILED)" in workflow

    code_start = retry.index("<<'PY'\n") + len("<<'PY'\n")
    code_end = retry.index("\nPY\n)", code_start)
    validator_source = retry[code_start:code_end]

    def run_validator(archive_path, destination):
        return subprocess.run(
            [sys.executable, "-c", validator_source, str(archive_path), str(destination)],
            capture_output=True, text=True, timeout=5, check=False,
        )

    good_archive = tmp_path / "good.zip"
    with zipfile.ZipFile(good_archive, "w") as archive:
        archive.writestr("aws/install", "#!/bin/sh\n")
    good_dest = tmp_path / "good-dest"
    good_result = run_validator(good_archive, good_dest)
    assert good_result.returncode == 0
    assert good_result.stdout.strip() == "PASS"
    assert (good_dest / "aws/install").is_file()

    invalid_archive = tmp_path / "invalid.zip"
    invalid_archive.write_bytes(b"not-a-zip")
    invalid_result = run_validator(invalid_archive, tmp_path / "invalid-dest")
    assert invalid_result.stdout.strip() == "INVALID_ZIP"

    blocked_dest = tmp_path / "not-a-directory"
    blocked_dest.write_text("x", encoding="utf-8")
    io_result = run_validator(good_archive, blocked_dest)
    assert io_result.stdout.strip() == "OS_ERROR"
    assert str(blocked_dest) not in io_result.stdout
    assert re.fullmatch(r"(PASS|INVALID_ZIP|OS_ERROR)", io_result.stdout.strip())

from scripts.sanitize_cn_tickflow_deploy_invocation import project


def test_projects_only_bounded_status_and_safe_failure_categories():
    raw = {
        "Status": "Failed",
        "StatusDetails": "Failed",
        "ResponseCode": 1,
        "StandardOutputContent": "CN_TICKFLOW_ROLLBACK=ATTEMPTED\n",
        "StandardErrorContent": "pip ERROR: No matching distribution found\nsecret=not-for-logs",
    }
    result = project(raw)
    assert "CN_TICKFLOW_COMMAND_STATUS=Failed" in result
    assert "CN_TICKFLOW_FAILURE_CLASS=PYTHON_DEPENDENCY" in result
    assert "CN_TICKFLOW_ROLLBACK=ATTEMPTED" in result
    assert all("secret" not in line and "not-for-logs" not in line for line in result)


def test_projects_installer_stage_without_raw_remote_text():
    raw = {
        "Status": "Failed",
        "StatusDetails": "Failed",
        "ResponseCode": 1,
        "StandardOutputContent": "",
        "StandardErrorContent": "CN_TICKFLOW_INSTALL_FAILED_STAGE=PIP_INSTALL\nprivate details",
    }
    result = project(raw)
    assert "CN_TICKFLOW_INSTALL_FAILED_STAGE=PIP_INSTALL" in result
    assert "CN_TICKFLOW_FAILURE_CLASS=INSTALLER_UNKNOWN_STAGE" in result
    assert not any("private details" in line for line in result)


def test_rejects_unbounded_status_tokens_and_response_codes():
    result = project({
        "Status": "Failed\nsecret",
        "StatusDetails": "x" * 100,
        "ResponseCode": 9999,
        "StandardOutputContent": "",
        "StandardErrorContent": "",
    })
    assert "CN_TICKFLOW_COMMAND_STATUS=UNKNOWN" in result
    assert "CN_TICKFLOW_COMMAND_STATUS_DETAILS=UNKNOWN" in result
    assert "CN_TICKFLOW_RESPONSE_CODE=UNKNOWN" in result

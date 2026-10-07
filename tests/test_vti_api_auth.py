from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.v1.endpoints import data as data_endpoint


def _request(cookies=None):
    return SimpleNamespace(cookies=cookies or {})


def test_vti_auth_fails_closed_when_admin_auth_disabled(monkeypatch):
    monkeypatch.setattr(data_endpoint, "is_auth_enabled", lambda: False)

    with pytest.raises(HTTPException) as exc:
        data_endpoint._require_vti_session(_request())

    assert exc.value.status_code == 503


def test_vti_auth_requires_valid_http_only_session(monkeypatch):
    monkeypatch.setattr(data_endpoint, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(data_endpoint, "verify_session", lambda value: value == "good")

    with pytest.raises(HTTPException) as missing:
        data_endpoint._require_vti_session(_request())
    assert missing.value.status_code == 401

    with pytest.raises(HTTPException) as bad:
        data_endpoint._require_vti_session(
            _request({data_endpoint.COOKIE_NAME: "bad"})
        )
    assert bad.value.status_code == 401

    data_endpoint._require_vti_session(
        _request({data_endpoint.COOKIE_NAME: "good"})
    )

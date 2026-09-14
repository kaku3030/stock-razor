import pytest

from data_provider.base import DataFetchError
from data_provider.baostock_fetcher import BaostockFetcher


class _Result:
    def __init__(self, code="0", message=""):
        self.error_code = code
        self.error_msg = message


class _FakeBaostock:
    def __init__(self, login_result):
        self.login_result = login_result
        self.logout_calls = 0

    def login(self):
        return self.login_result

    def logout(self):
        self.logout_calls += 1
        return _Result()


def test_baostock_login_failure_is_explicit_and_logout_runs():
    module = _FakeBaostock(_Result("100", "offline"))
    fetcher = BaostockFetcher()
    fetcher._bs_module = module

    with pytest.raises(DataFetchError, match="登录失败"):
        with fetcher._baostock_session():
            pass

    assert module.logout_calls == 1


def test_baostock_session_releases_on_body_exception():
    module = _FakeBaostock(_Result())
    fetcher = BaostockFetcher()
    fetcher._bs_module = module

    with pytest.raises(RuntimeError, match="boom"):
        with fetcher._baostock_session():
            raise RuntimeError("boom")

    assert module.logout_calls == 1


class _MalformedBaostock:
    def __init__(self):
        self.logout_calls = 0

    def login(self):
        return object()

    def logout(self):
        self.logout_calls += 1
        return object()


def test_baostock_malformed_login_result_is_normalized():
    module = _MalformedBaostock()
    fetcher = BaostockFetcher()
    fetcher._bs_module = module

    with pytest.raises(DataFetchError, match="登录失败"):
        with fetcher._baostock_session():
            pass

    assert module.logout_calls == 1

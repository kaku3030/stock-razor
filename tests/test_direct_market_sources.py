from scripts.check_direct_market_sources import check


class _Fetcher:
    def __init__(self, name, rows=3, error=None):
        self.name = name
        self.rows = rows
        self.error = error

    def get_daily_data(self, symbol, days):
        if self.error:
            raise self.error
        return type("Frame", (), {"__len__": lambda self: 3, "columns": ["date", "close"]})()


def test_check_returns_zero_when_all_sources_succeed(capsys):
    assert check((_Fetcher("TencentFetcher"), _Fetcher("SinaResearchFetcher")), "600000", 5) == 0
    output = capsys.readouterr().out
    assert "TencentFetcher: rows=3" in output
    assert "SinaResearchFetcher: rows=3" in output


def test_check_returns_nonzero_and_reports_provider_failure(capsys):
    assert check((_Fetcher("TencentFetcher", error=TimeoutError("offline")),), "600000", 5) == 1
    assert "TencentFetcher: ERROR TimeoutError: offline" in capsys.readouterr().out

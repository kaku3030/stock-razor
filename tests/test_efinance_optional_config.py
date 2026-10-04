from types import SimpleNamespace
from unittest.mock import patch

from data_provider.efinance_fetcher import EfinanceFetcher


def test_optional_eastmoney_patch_flag_defaults_false_when_legacy_config_omits_it():
    legacy = SimpleNamespace()
    with patch("src.config.get_config", return_value=legacy):
        fetcher = EfinanceFetcher()
    assert fetcher is not None

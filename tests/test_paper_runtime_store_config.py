import pytest

from src.services.execution_engine import ExecutionBlocked
from src.services.paper_runtime_store_config import PaperRuntimeStoreConfig


def test_store_config_requires_both_paths():
    with pytest.raises(ExecutionBlocked, match="paths are required"):
        PaperRuntimeStoreConfig.from_env({})


def test_store_config_rejects_memory_and_shared_paths():
    with pytest.raises(ExecutionBlocked, match="durable"):
        PaperRuntimeStoreConfig.from_env(
            {
                "PAPER_EXECUTION_STORE_PATH": ":memory:",
                "PAPER_SHADOW_STORE_PATH": "/var/lib/stock-razor/shadow.sqlite",
            }
        )
    with pytest.raises(ExecutionBlocked, match="separate"):
        PaperRuntimeStoreConfig.from_env(
            {
                "PAPER_EXECUTION_STORE_PATH": "/var/lib/stock-razor/runtime.sqlite",
                "PAPER_SHADOW_STORE_PATH": "/var/lib/stock-razor/runtime.sqlite",
            }
        )


def test_store_config_is_pure_and_reports_distinct_durable_paths(tmp_path):
    execution = tmp_path / "runtime.sqlite"
    shadow = tmp_path / "shadow.sqlite"

    config = PaperRuntimeStoreConfig.from_env(
        {
            "PAPER_EXECUTION_STORE_PATH": str(execution),
            "PAPER_SHADOW_STORE_PATH": str(shadow),
        }
    )

    assert config.execution_path == execution
    assert config.shadow_path == shadow
    assert config.status() == "CONFIGURED_DISTINCT_DURABLE_PATHS"
    assert not execution.exists()
    assert not shadow.exists()
